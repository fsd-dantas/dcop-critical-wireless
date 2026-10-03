# dcop-critical-wireless

Distributed channel assignment for a mission-critical (public-safety) radio network,
modelled as a Distributed Constraint Optimization Problem (DCOP) and solved with
**DPOP** (Dynamic Programming Optimization Protocol, Petcu & Faltings, 2005).

## Problem

Each region of a map is served by one radio site controlled by an autonomous agent.
Adjacent regions share a coverage border, so they must not use the same channel group
(co-channel interference). With four channel groups this is the map-colouring problem,
and the Four Colour Theorem guarantees a solution for any planar map.

| Map colouring        | Wireless network                         |
|----------------------|------------------------------------------|
| Region               | Coverage area of a radio site            |
| Shared border        | Overlapping coverage (interference risk) |
| Colour               | Channel group                            |
| Agent                | Autonomous site controller               |
| Constraint f(xi, xj) | Co-channel interference penalty          |

The network is hypothetical; only the geography is real.

## Maps

- `data/curitiba_regionais.json` — the 10 administrative regions (Regionais) of Curitiba.
- `data/rmc_municipalities.json` — the 29 municipalities of the Curitiba Metropolitan Region.

Two regions are adjacent only if their boundaries share a segment; touching at a single
point does not count.

## Layout

```
data/    adjacency graphs (JSON)
dpop/    DCOP model, pseudo-tree, agents, runner
viz/     map and message-trace rendering
tools/   one-off geodata → adjacency extraction
tests/   correctness tests
```

## Setup

```
pip install -r requirements.txt
```
