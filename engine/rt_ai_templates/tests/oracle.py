#!/usr/bin/env python3
"""Independent event oracle for RT-AI admission scenarios."""

import random
import subprocess
import sys


def reference(now, jobs, candidate):
    all_jobs = [*jobs, (now, *candidate)]
    states = [[0, 0] for _ in all_jobs]
    finishes = [[0, 0] for _ in all_jobs]
    busy = [0, 0]
    remaining = 2 * len(all_jobs)
    time = now
    while remaining:
        for j in range(len(all_jobs)):
            for s in range(2):
                if states[j][s] == 1 and finishes[j][s] <= time:
                    states[j][s] = 2
                    remaining -= 1
        for resource in range(2):
            if busy[resource] > time:
                continue
            ready = []
            for j, (release, deadline, cost0, resource0, cost1, resource1) in enumerate(all_jobs):
                for s, (cost, selected) in enumerate(((cost0, resource0), (cost1, resource1))):
                    if release <= time and states[j][s] == 0 and selected == resource and (s == 0 or states[j][0] == 2):
                        ready.append((deadline, j, s, cost))
            if ready:
                _, j, s, cost = min(ready)
                states[j][s] = 1
                finishes[j][s] = time + cost
                busy[resource] = time + cost
        if not remaining:
            break
        future = [finishes[j][s] for j in range(len(all_jobs)) for s in range(2) if states[j][s] == 1 and finishes[j][s] > time]
        future += [job[0] for job in all_jobs if job[0] > time]
        if not future:
            return -7, 0
        time = min(future)
    accepted = all(max(finishes[j]) <= job[1] for j, job in enumerate(all_jobs))
    return (0 if accepted else -7), max(finishes[-1])


def main():
    rng = random.Random(0xCECA2026)
    rows, expected = [], []
    for scenario in range(10000):
        now = rng.randrange(50)
        jobs = []
        for _ in range(rng.randrange(4)):
            release = now + rng.randrange(15)
            costs = rng.randrange(1, 15), rng.randrange(1, 15)
            resources = rng.randrange(2), rng.randrange(2)
            deadline = max(release + 1, release + sum(costs) + rng.randrange(-5, 25))
            jobs.append((release, deadline, costs[0], resources[0], costs[1], resources[1]))
        costs = rng.randrange(1, 15), rng.randrange(1, 15)
        resources = rng.randrange(2), rng.randrange(2)
        candidate = (max(now + 1, now + sum(costs) + rng.randrange(-5, 25)), costs[0], resources[0], costs[1], resources[1])
        rows.append(" ".join(map(str, [scenario, now, len(jobs), *(v for job in jobs for v in job), *candidate])))
        expected.append(reference(now, jobs, candidate))
    run = subprocess.run([sys.argv[1]], input="\n".join(rows) + "\n", text=True, stdout=subprocess.PIPE, check=True)
    actual = run.stdout.splitlines()
    assert len(actual) == len(expected)
    for scenario, (row, wanted) in enumerate(zip(actual, expected)):
        _, status, finish = map(int, row.split())
        assert (status, finish) == wanted, f"scenario {scenario}: runtime={(status, finish)} oracle={wanted}"
    print("INDEPENDENT_10000_SCENARIO_ORACLE_PASS")


if __name__ == "__main__":
    main()
