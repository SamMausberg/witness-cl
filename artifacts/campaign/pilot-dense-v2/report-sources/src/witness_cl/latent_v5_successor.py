"""Post-hoc development successor: close zero-information weak-dominance plateaus.

This was designed after the failed v5 holdout and is not its frozen algorithm.
It changes only a zero-debit stalled selection. Exact weak dominance is enough
for monotone retention; requiring positive lower gain can leave a common optimum
unused when some compatible worlds make it tie the incumbent.
"""
from .latent import compare
from .latent_agent import EpisodeTicket
from .latent_v5 import DecisionDirectedAgent


class WeakDominanceClosureAgent(DecisionDirectedAgent):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.weak_promotions = 0

    def choose(self, goal):
        previous_promotions = self.promotions
        ticket = super().choose(goal)
        if (ticket.debit != 0 or ticket.program != ticket.incumbent or
                self.last_information_gain != 0 or self.promotions != previous_promotions):
            return ticket
        rank = self.proposer.rank(goal, trainable=self.trainable)
        if self.proposals is not None:
            rank = rank[:self.proposals]
        admitted = []
        for j in rank:
            if j == ticket.incumbent:
                continue
            c = compare(self.space, self.programs[j], self.programs[ticket.incumbent],
                        self.rewards[goal], max_nodes=self.max_nodes)
            self.comparisons += 1; self.nodes += c.nodes
            self.unknown += c.status == 'unknown'
            if c.admits and c.upper > 0:
                admitted.append((c.lower, c.upper, -rank.index(j), j))
        if not admitted:
            return ticket
        lower, _, _, chosen = max(admitted)
        self.incumbents[goal] = chosen
        self.promotions += 1; self.weak_promotions += lower == 0
        self.certificates.append((self.episodes, goal, ticket.incumbent, chosen, lower))
        self.pending = EpisodeTicket(ticket.index, goal, chosen, chosen, 0,
                                     ticket.generation, ticket.era)
        return self.pending
