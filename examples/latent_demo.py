"""Twelve online episodes; the learner never receives the environment table."""
from itertools import product
from witness_cl.latent import Machine, Program, LatentSpace
from witness_cl.latent_agent import LatentAgent


def main() -> None:
    # Only the environment driver can inspect this table.
    environment = Machine(2, 2, 2, ((0, 0), (1, 0), (0, 1), (1, 1)))
    programs = tuple(Program.word(word, 2) for word in product(range(2), repeat=4))
    agent = LatentAgent(LatentSpace(2, 2, 2), programs, ((0, 2),), budget=16, seed=0)
    for episode in range(12):
        ticket = agent.choose(0)
        trace = programs[ticket.program].rollout(environment)
        agent.observe(ticket, trace)
        print(f"episode={episode:02d} program={ticket.program:02d} "
              f"return={sum(2*o for _,o in trace)} debit={ticket.debit} "
              f"spent={agent.spent} partial_models={len(agent.space.partials)}")


if __name__ == '__main__':
    main()
