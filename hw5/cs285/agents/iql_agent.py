from typing import Optional
import torch
from torch import nn
from cs285.agents.awac_agent import AWACAgent

from typing import Callable, Optional, Sequence, Tuple, List


class IQLAgent(AWACAgent):
    def __init__(
        self,
        observation_shape: Sequence[int],
        num_actions: int,
        make_value_critic: Callable[[Tuple[int, ...], int], nn.Module],
        make_value_critic_optimizer: Callable[
            [torch.nn.ParameterList], torch.optim.Optimizer
        ],
        expectile: float,
        **kwargs,
    ):
        super().__init__(
            observation_shape=observation_shape, num_actions=num_actions, **kwargs
        )

        self.value_critic = make_value_critic(observation_shape)
        self.target_value_critic = make_value_critic(observation_shape)
        self.target_value_critic.load_state_dict(self.value_critic.state_dict())

        self.value_critic_optimizer = make_value_critic_optimizer(
            self.value_critic.parameters()
        )
        self.expectile = expectile

    def compute_advantage(
        self,
        observations: torch.Tensor,
        actions: torch.Tensor,
        action_dist: Optional[torch.distributions.Categorical] = None,
    ):
        # TODO(student): Compute advantage with IQL
        qa_values = self.target_critic(observations)
        q_values = torch.gather(qa_values, dim=1, index=actions.unsqueeze(1)).squeeze(1)
        values = self.target_value_critic(observations)
        advantages = q_values - values.squeeze(1)
        return advantages

    def update_q(
        self,
        observations: torch.Tensor,
        actions: torch.Tensor,
        rewards: torch.Tensor,
        next_observations: torch.Tensor,
        dones: torch.Tensor,
    ) -> dict:
        """
        Update Q(s, a)
        """
        # TODO(student): Update Q(s, a) to match targets (based on V)
        q_values = torch.gather(
            self.critic(observations), dim=1, index=actions.unsqueeze(1)
        ).squeeze(1)

        target_values = rewards + torch.where(
            dones > 0.0,
            0.0,
            self.discount * self.target_value_critic(next_observations).squeeze(-1),
        )
        assert q_values.shape == target_values.shape
        loss = self.critic_loss(q_values, target_values)

        self.critic_optimizer.zero_grad()
        loss.backward()
        grad_norm = torch.nn.utils.clip_grad.clip_grad_norm_(
            self.critic.parameters(), self.clip_grad_norm or float("inf")
        )
        self.critic_optimizer.step()

        metrics = {
            "q_loss": loss.item(),
            "q_values": q_values.mean().item(),
            "target_values": target_values.mean().item(),
            "q_grad_norm": grad_norm.item(),
        }

        return metrics

    @staticmethod
    def iql_expectile_loss(
        expectile: float, vs: torch.Tensor, target_qs: torch.Tensor
    ) -> torch.Tensor:
        """
        Compute the expectile loss for IQL
        """
        # TODO(student): Compute the expectile loss

        diff = target_qs - vs
        return (torch.where(diff > 0, expectile, expectile - 1).abs() * diff**2).mean()

    def update_v(
        self,
        observations: torch.Tensor,
        actions: torch.Tensor,
    ):
        """
        Update the value network V(s) using targets Q(s, a)
        """
        # TODO(student): Compute target values for V(s)
        target_values = torch.gather(
            self.target_critic(observations), dim=1, index=actions.unsqueeze(1)
        ).squeeze(1)
        vs = self.value_critic(observations).squeeze(1)
        assert vs.shape == target_values.shape
        # TODO(student): Update V(s) using the loss from the IQL paper
        loss = self.iql_expectile_loss(self.expectile, vs, target_values)

        self.value_critic_optimizer.zero_grad()
        loss.backward()
        grad_norm = torch.nn.utils.clip_grad.clip_grad_norm_(
            self.value_critic.parameters(), self.clip_grad_norm or float("inf")
        )
        self.value_critic_optimizer.step()

        return {
            "v_loss": loss.item(),
            "vs_adv": (vs - target_values).mean().item(),
            "vs": vs.mean().item(),
            "target_values": target_values.mean().item(),
            "v_grad_norm": grad_norm.item(),
        }

    def update_critic(
        self,
        observations: torch.Tensor,
        actions: torch.Tensor,
        rewards: torch.Tensor,
        next_observations: torch.Tensor,
        dones: torch.Tensor,
    ) -> dict:
        """
        Update both Q(s, a) and V(s)
        """
        metrics_q = self.update_q(
            observations, actions, rewards, next_observations, dones
        )
        metrics_v = self.update_v(observations, actions)

        return {**metrics_q, **metrics_v}

    def update(
        self,
        observations: torch.Tensor,
        actions: torch.Tensor,
        rewards: torch.Tensor,
        next_observations: torch.Tensor,
        dones: torch.Tensor,
        step: int,
    ):
        metrics = self.update_critic(
            observations, actions, rewards, next_observations, dones
        )
        metrics["actor_loss"] = self.update_actor(observations, actions)

        if step % self.target_update_period == 0:
            self.update_target_critic()
            self.update_target_value_critic()

        return metrics

    def update_target_value_critic(self):
        self.target_value_critic.load_state_dict(self.value_critic.state_dict())
