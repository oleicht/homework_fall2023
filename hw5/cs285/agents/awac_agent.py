from typing import Callable, Optional, Sequence, Tuple, List
import torch
from torch import nn


from cs285.agents.dqn_agent import DQNAgent


class AWACAgent(DQNAgent):
    def __init__(
        self,
        observation_shape: Sequence[int],
        num_actions: int,
        make_actor: Callable[[Tuple[int, ...], int], nn.Module],
        make_actor_optimizer: Callable[[torch.nn.ParameterList], torch.optim.Optimizer],
        temperature: float,
        **kwargs,
    ):
        super().__init__(
            observation_shape=observation_shape, num_actions=num_actions, **kwargs
        )

        self.actor = make_actor(observation_shape, num_actions)
        self.actor_optimizer = make_actor_optimizer(self.actor.parameters())
        self.temperature = temperature

    def compute_critic_loss(
        self,
        observations: torch.Tensor,
        actions: torch.Tensor,
        rewards: torch.Tensor,
        next_observations: torch.Tensor,
        dones: torch.Tensor,
    ):
        with torch.no_grad():
            # TODO(student): compute the actor distribution, then use it to compute E[Q(s, a)]
            next_qa_values = self.target_critic(next_observations)

            # Use the actor to compute a critic backup
            next_qs = (next_qa_values * self.actor(next_observations).probs).sum(dim=-1)

            # TODO(student): Compute the TD target
            target_values = rewards + self.discount * torch.where(
                dones > 0, 0.0, next_qs
            )

        # TODO(student): Compute Q(s, a) and loss similar to DQN
        qa_values = self.critic(observations)
        q_values = torch.gather(qa_values, dim=1, index=actions.unsqueeze(1)).squeeze(
            1
        )  # Compute from the data actions; see torch.gather)
        assert q_values.shape == target_values.shape

        loss = self.critic_loss(q_values, target_values)

        return (
            loss,
            {
                "critic_loss": loss.item(),
                "q_values": q_values.mean().item(),
                "target_values": target_values.mean().item(),
            },
            {
                "qa_values": qa_values,
                "q_values": q_values,
            },
        )

    def compute_advantage(
        self,
        observations: torch.Tensor,
        actions: torch.Tensor,
        action_dist: Optional[torch.distributions.Categorical] = None,
    ):
        # TODO(student): compute the advantage of the actions compared to E[Q(s, a)]
        qa_values = self.target_critic(observations)
        q_values = torch.gather(qa_values, dim=1, index=actions.unsqueeze(1)).squeeze(1)

        values = (action_dist.probs * qa_values).sum(dim=-1)

        advantages = q_values - values
        return advantages

    def update_actor(
        self,
        observations: torch.Tensor,
        actions: torch.Tensor,
    ):
        # TODO(student): update the actor using AWAC
        loss = (
            -self.actor(observations).log_prob(actions)
            * (
                self.compute_advantage(observations, actions, self.actor(observations))
                / self.temperature
            )
            .exp()
            .detach()
        ).mean()

        self.actor_optimizer.zero_grad()
        loss.backward()
        self.actor_optimizer.step()

        return loss.item()

    def update(
        self,
        observations: torch.Tensor,
        actions: torch.Tensor,
        rewards: torch.Tensor,
        next_observations: torch.Tensor,
        dones: torch.Tensor,
        step: int,
    ):
        metrics = super().update(
            observations, actions, rewards, next_observations, dones, step
        )

        # Update the actor.
        actor_loss = self.update_actor(observations, actions)
        metrics["actor_loss"] = actor_loss

        return metrics
