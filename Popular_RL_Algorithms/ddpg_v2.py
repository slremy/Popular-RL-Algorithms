'''
DDPG
'''


import math
import random

import gym
import numpy as np

import torch
import torch.nn as nn
import torch.optim as optim
import torch.nn.functional as F
from torch.distributions import Normal
from torch.distributions import Categorical
from collections import namedtuple
from common.buffers import ReplayBuffer
from common.value_networks import QNetwork
from common.policy_networks import DPG_PolicyNetwork

import matplotlib.pyplot as plt
from matplotlib import animation
import argparse
from gym import spaces



GPU = True
device_idx = 0
if GPU:
    device = torch.device("cuda:" + str(device_idx) if torch.cuda.is_available() else "cpu")
else:
    device = torch.device("cpu")
print(device)

def parse_args():
    parser = argparse.ArgumentParser(description='Train or test neural net motor controller.')
    parser.add_argument('--train', dest='train', action='store_true', default=False)
    parser.add_argument('--test', dest='test', action='store_true', default=False)

    args = parser.parse_args()
    return args

class DDPG():
    def __init__(self, env, replay_buffer_size, hidden_dim, q_lr=8e-4, policy_lr = 8e-4):
        state_space = env.observation_space 
        action_space = env.action_space
        self.replay_buffer = ReplayBuffer(replay_buffer_size)
        self.qnet = QNetwork(state_space, action_space, hidden_dim).to(device)
        self.target_qnet = QNetwork(state_space, action_space, hidden_dim).to(device)
        self.policy_net = DPG_PolicyNetwork(state_space, action_space, hidden_dim).to(device)
        self.target_policy_net = DPG_PolicyNetwork(state_space, action_space, hidden_dim).to(device)

        print('Q network: ', self.qnet)
        print('Policy network: ', self.policy_net)

        for target_param, param in zip(self.target_qnet.parameters(), self.qnet.parameters()):
            target_param.data.copy_(param.data)
        self.q_criterion = nn.MSELoss()
        
        self.update_cnt=0

        self.q_optimizer = optim.Adam(self.qnet.parameters(), lr=q_lr)
        self.policy_optimizer = optim.Adam(self.policy_net.parameters(), lr=policy_lr)
    
    def target_soft_update(self, net, target_net, soft_tau):
    # Soft update the target net
        for target_param, param in zip(target_net.parameters(), net.parameters()):
            target_param.data.copy_(  # copy data value into target parameters
                target_param.data * (1.0 - soft_tau) + param.data * soft_tau
            )
        return target_net

    def update(self, batch_size, reward_scale=10.0, gamma=0.99, soft_tau=1e-2, policy_up_itr=10, target_update_delay=3, warmup=True):
        self.update_cnt+=1
        state, action, reward, next_state, done = self.replay_buffer.sample(batch_size)
        # print('sample:', state, action,  reward, done)

        state      = torch.FloatTensor(state).to(device)
        next_state = torch.FloatTensor(next_state).to(device)
        action     = torch.FloatTensor(action).to(device)
        reward     = torch.FloatTensor(reward).unsqueeze(1).to(device)  
        done       = torch.FloatTensor(np.float32(done)).unsqueeze(1).to(device)

        predict_q = self.qnet(state, action) # for q 
        new_next_action = self.target_policy_net.evaluate(next_state)  # for q
        new_action = self.policy_net.evaluate(state) # for policy
        predict_new_q = self.qnet(state, new_action) # for policy
        target_q = reward+(1-done)*gamma*self.target_qnet(next_state, new_next_action)  # for q
        # reward = reward_scale * (reward - reward.mean(dim=0)) /reward.std(dim=0) # normalize with batch mean and std

        # train qnet
        q_loss = self.q_criterion(predict_q, target_q.detach())
        self.q_optimizer.zero_grad()
        q_loss.backward()
        self.q_optimizer.step()

        # train policy_net
        policy_loss = -torch.mean(predict_new_q)
        self.policy_optimizer.zero_grad()
        policy_loss.backward()
        self.policy_optimizer.step()

            
        # update the target_qnet
        if self.update_cnt%target_update_delay==0:
            self.target_qnet=self.target_soft_update(self.qnet, self.target_qnet, soft_tau)
            self.target_policy_net=self.target_soft_update(self.policy_net, self.target_policy_net, soft_tau)

        return q_loss.detach().cpu().numpy(), policy_loss.detach().cpu().numpy()

    def save_model(self, path):
        torch.save(self.qnet.state_dict(), path+'_q')
        torch.save(self.target_qnet.state_dict(), path+'_target_q')
        torch.save(self.policy_net.state_dict(), path+'_policy')

    def load_model(self, path):
        self.qnet.load_state_dict(torch.load(path+'_q'))
        self.target_qnet.load_state_dict(torch.load(path+'_target_q'))
        self.policy_net.load_state_dict(torch.load(path+'_policy'))
        self.qnet.eval()
        self.target_qnet.eval()
        self.policy_net.eval()

def plot(rewards):
    plt.figure(figsize=(20,5))
    plt.plot(rewards)
    plt.savefig('ddpg.png')
    # plt.show()
    plt.clf()

def train(env, model, episodes=10000, steps=100, explore_steps=0, batch_size=256, frame_idx=0, model_path='./model/ddpg'):
    rewards = []

    # training loop
    for eps in range(episodes):
        q_loss_list=[]
        policy_loss_list=[]
        state, _ = env.reset()
        episode_reward = 0
        
        for step in range(steps):

            if frame_idx > explore_steps:
                action = model.policy_net.get_action(state)
            else:
                action = model.policy_net.sample_action()
            next_state, reward, done, truncated, _ = env.step(action)
            
            model.replay_buffer.push(state, action, reward, next_state, done)
            
            state = next_state
            episode_reward += reward
            frame_idx += 1
            
            if len(model.replay_buffer) > batch_size:
                q_loss, policy_loss = model.update(batch_size)
                q_loss_list.append(q_loss)
                policy_loss_list.append(policy_loss)
            
            if done:
                break

        if eps % 20 == 0:
            plot(rewards)
            model.save_model(model_path)
        print('Eps: ', eps, '| Reward: ', episode_reward, '| Loss: ', np.average(q_loss_list), np.average(policy_loss_list))
        
        rewards.append(episode_reward)
    model.save_model(model_path)

    return model

class NormalizedActions(gym.ActionWrapper): # gym env wrapper
    def action(self, action):
        low  = self.action_space.low
        high = self.action_space.high
        
        action = low + (action + 1.0) * 0.5 * (high - low)
        action = np.clip(action, low, high)
        
        return action

    def reverse_action(self, action):
        low  = self.action_space.low
        high = self.action_space.high
        
        action = 2 * (action - low) / (high - low) - 1
        action = np.clip(action, low, high)
        
        return action


if __name__ == '__main__':
    args = parse_args()
    NUM_JOINTS=2
    LINK_LENGTH=[200, 140]
    INI_JOING_ANGLES=[0.1, 0.1]
    SCREEN_SIZE=1000
    # SPARSE_REWARD=False
    # SCREEN_SHOT=False
    ENV = ['Pendulum'][0]
    if ENV == 'Pendulum':
        env = NormalizedActions(gym.make("Pendulum-v1"))
        # env = gym.make("Pendulum-v0")
    hidden_dim = 64
    explore_steps = 0  # for random exploration
    batch_size = 64

    replay_buffer_size=1e6
    model_path='./model/ddpg'
    torch.autograd.set_detect_anomaly(True)
    alg = DDPG(env, replay_buffer_size, hidden_dim)

    if args.train:
        # alg.load_model(model_path)
        alg = train(env, alg, episodes=1000)

    if args.test:
        test_episodes = 10
        max_steps=100
        alg.load_model(model_path)

        for i_episode in range (test_episodes):
            q_loss_list=[]
            policy_loss_list=[]
            state, _ = env.reset()
            episode_reward = 0

            for step in range(max_steps):
                action = alg.policy_net.get_action(state, noise_scale=0.0)  # no noise for testing
                next_state, reward, done, truncated, _ = env.step(action)
                
                state = next_state
                episode_reward += reward
                
                
                if done:
                    break
 
            print('Eps: ', i_episode, '| Reward: ', episode_reward)
            
