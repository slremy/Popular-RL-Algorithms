
#!/usr/bin/env python

from setuptools import setup, find_packages

setup(name='Popular_RL_Algorithms',
      version='0.1',
      description='PyTorch implementation of Soft Actor-Critic (SAC), Twin Delayed DDPG (TD3), Actor-Critic (AC/A2C), Proximal Policy Optimization (PPO), QT-Opt, PointNet..',
      author='quantumiracle',
      author_email='https://github.com/quantumiracle',
      url='https://github.com/quantumiracle/Popular-RL-Algorithms',
      install_requires = ["gym", 
          ],
      packages=find_packages(),
)
