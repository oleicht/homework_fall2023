import time
import argparse
import pickle

from cs285.agents import agents as agent_types
from cs285.envs import Pointmass

import os
import time

import gym
import numpy as np
import torch
from cs285.infrastructure import pytorch_util as ptu
import tqdm

from cs285.infrastructure import utils
from cs285.infrastructure.logger import Logger
from cs285.infrastructure.replay_buffer import ReplayBuffer

from cs285.scripts.scripting_utils import make_logger, make_config
from cs285.scripts.run_hw5_explore import visualize

MAX_NVIDEO = 2


def run_training_loop(config: dict, logger: Logger, args: argparse.Namespace):
    # set random seeds
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    ptu.init_gpu(use_gpu=not args.no_gpu, gpu_id=args.which_gpu)

    # make the gym environment
    env = config["make_env"]()
    eval_env = config["make_env"]()
    render_env = config["make_env"]()
    exploration_schedule = config.get("exploration_schedule", None)
    discrete = isinstance(env.action_space, gym.spaces.Discrete)

    assert discrete, "DQN only supports discrete action spaces"

    agent_cls = agent_types[config["agent"]]
    agent = agent_cls(
        env.observation_space.shape,
        env.action_space.n,
        **config["agent_kwargs"],
    )

    ep_len = env.spec.max_episode_steps or env.max_episode_steps

    observation = None

    # Replay buffer
    replay_buffer = ReplayBuffer(capacity=config["total_steps"])

    with open(
        os.path.join(args.dataset_dir, f"{config['dataset_name']}.pkl"), "rb"
    ) as f:
        replay_buffer_disk: ReplayBuffer = pickle.load(f)

    for o, a, r, no, d in zip(
        replay_buffer_disk.observations,
        replay_buffer_disk.actions,
        replay_buffer_disk.rewards,
        replay_buffer_disk.next_observations,
        replay_buffer_disk.dones,
    ):
        replay_buffer.insert(o, a, r, no, d)

    observation = env.reset()

    recent_observations = []

    num_offline_steps = config["offline_steps"]
    num_online_steps = config["total_steps"] - num_offline_steps
    epsilon = None

    for step in tqdm.trange(config["total_steps"], dynamic_ncols=True):
        # TODO(student): Borrow code from another online training script here. Only run the online training loop after `num_offline_steps` steps.
        if step > num_offline_steps:
            epsilon = 0.0  # 02
            action = agent.get_action(observation, epsilon=epsilon)
            # Step the environment and add the data to the replay buffer
            next_observation, reward, done, info = env.step(action)
            next_observation = np.asarray(next_observation)
            replay_buffer.insert(
                observation=observation,
                action=action,
                reward=reward,
                next_observation=next_observation,
                done=done and not info.get("TimeLimit.truncated", False),
            )
            recent_observations.append(observation)
            if done:
                observation = env.reset()

                logger.log_scalar(info["episode"]["r"], "train_return", step)
                logger.log_scalar(info["episode"]["l"], "train_ep_len", step)
            else:
                observation = next_observation

        # Main training loop
        batch = replay_buffer.sample(config["batch_size"])

        # Convert to PyTorch tensors
        batch = ptu.from_numpy(batch)

        update_info = agent.update(
            batch["observations"],
            batch["actions"],
            100
            * (batch["rewards"] + 1),  # transform rewards to improve training dynamics
            batch["next_observations"],
            batch["dones"],
            step,
        )

        # Logging code
        if epsilon is not None:
            update_info["epsilon"] = epsilon

        if step % args.log_interval == 0:
            for k, v in update_info.items():
                logger.log_scalar(v, k, step)
            logger.flush()

        if step % args.eval_interval == 0:
            # Evaluate
            trajectories = utils.sample_n_trajectories(
                eval_env,
                agent,
                args.num_eval_trajectories,
                ep_len,
            )
            returns = [t["episode_statistics"]["r"] for t in trajectories]
            ep_lens = [t["episode_statistics"]["l"] for t in trajectories]

            logger.log_scalar(np.mean(returns), "eval_return", step)
            logger.log_scalar(np.mean(ep_lens), "eval_ep_len", step)

            if len(returns) > 1:
                logger.log_scalar(np.std(returns), "eval/return_std", step)
                logger.log_scalar(np.max(returns), "eval/return_max", step)
                logger.log_scalar(np.min(returns), "eval/return_min", step)
                logger.log_scalar(np.std(ep_lens), "eval/ep_len_std", step)
                logger.log_scalar(np.max(ep_lens), "eval/ep_len_max", step)
                logger.log_scalar(np.min(ep_lens), "eval/ep_len_min", step)

        if step % args.visualize_interval == 0 and len(recent_observations) > 0:
            env_pointmass: Pointmass = render_env.unwrapped
            observations = np.stack(recent_observations)
            recent_observations = []
            logger.log_figure(
                visualize(env_pointmass, agent, observations),
                "exploration_trajectories",
                step,
                "eval",
            )

    # Save the final dataset
    # dataset_file = os.path.join(args.dataset_dir, f"{config['dataset_name']}.pkl")
    # with open(dataset_file, "wb") as f:
    #     pickle.dump(replay_buffer, f)
    #     print("Saved dataset to", dataset_file)

    # Render final heatmap
    fig = visualize(
        env_pointmass, agent, replay_buffer.observations[: config["total_steps"]]
    )
    fig.suptitle("State coverage")
    from pathlib import Path

    root = Path("/workspace/homework_fall2023/hw5")
    filename = root / f"exploration/{config['log_name']}.png"
    fig.savefig(filename)
    print("Saved final heatmap to", filename)


banner = """
======================================================================
Exploration

Generating the dataset for the {env} environment using algorithm {alg}.
The results will be stored in {dataset_dir}.
======================================================================
"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config_file", "-cfg", type=str, required=True)

    parser.add_argument("--eval_interval", "-ei", type=int, default=10000)
    parser.add_argument("--visualize_interval", "-vi", type=int, default=1000)
    parser.add_argument("--num_eval_trajectories", "-neval", type=int, default=10)

    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--no_gpu", "-ngpu", action="store_true")
    parser.add_argument("--which_gpu", "-gpu_id", default=0)
    parser.add_argument("--log_interval", type=int, default=1)

    parser.add_argument("--use_reward", action="store_true")
    parser.add_argument("--dataset_dir", type=str, required=True)

    args = parser.parse_args()

    # create directory for logging
    logdir_prefix = "hw5_finetune_"  # keep for autograder

    config = make_config(args.config_file)
    logger = make_logger(logdir_prefix, config)

    os.makedirs(args.dataset_dir, exist_ok=True)
    print(
        banner.format(
            env=config["env_name"], alg=config["agent"], dataset_dir=args.dataset_dir
        )
    )

    run_training_loop(config, logger, args)


if __name__ == "__main__":
    main()
