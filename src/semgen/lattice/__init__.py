"""The generalization lattice over motif bundles (design §9): neighbours, guard, proofs, search and climbs.

Every candidate move must pass ``guard`` (floors, protected nodes, absent nodes, context edges; per changed
motif) and its order proof: ``check_order`` for a bundle of one, ``check_bundle_order`` (with the move's
certificate) otherwise. A failure raises; nothing is silently dropped. States are bundles, deduplicated by hash (a
bundle of one hashes as its motif). The search is bounded only by an explicit ``Budget`` (unbounded by default).

A bundle of one (and a bare ``Motif`` root) takes exactly today's single-motif path: ``neighbors`` with the
per-motif ``ALL_OPERATORS``, the per-node climb, and ``check_order`` of every candidate against the root. The bundle
operators (``BUNDLE_OPERATORS``) are not applied to a single plain part: no bundle move exists there (deletion
would be ``last_part``), so its output stays unchanged.
"""
from semgen.lattice.moves import BundleNeighbor, Neighbor, bundle_neighbors, neighbors, operators_of, state_hash
from semgen.lattice.policy import GeneralizationOrderError, PolicyViolation, bundle_guard, guard
from semgen.lattice.search import (
                                      Budget,
                                      Candidate,
                                      Lattice,
                                      LatticeEdge,
                                      NodeAxis,
                                      candidate_row,
                                      enumerate_lattice,
                                      json_line,
                                      state_space_estimate,
)
from semgen.order import OrderResult, check_bundle_order, check_order  # re-exported for callers of the old module

__all__ = ["Budget", "BundleNeighbor", "Candidate", "GeneralizationOrderError", "Lattice", "LatticeEdge",
           "Neighbor", "NodeAxis", "OrderResult", "PolicyViolation", "bundle_guard", "bundle_neighbors",
           "candidate_row", "check_bundle_order", "check_order", "enumerate_lattice", "guard", "json_line",
           "neighbors", "operators_of", "state_hash", "state_space_estimate"]
