"""Collection of utils for audit trails."""
from abc import ABC, abstractmethod

import datetime
import uuid
import warnings

import networkx as nx


from regraph.exceptions import RevisionError, RevisionWarning
from regraph.rules import compose_rules, Rule, _create_merging_rule
from regraph.primitives import relabel_node
from regraph.utils import keys_by_value


def _generate_new_commit_meta_data():
    time = datetime.datetime.now()
    commit_id = str(uuid.uuid4())
    return time, commit_id


class Versioning(ABC):
    """Class for version control.

    Attributes
    ----------
    _current_branch
        Name of the current branch
    _deltas : dict
        Dictionary with delta's to all other branches
    _heads : dict
    _revision_graph : networkx.DiGraph

    Methods
    -------
    branches()
    current_branch()
    commit(graph, rule, instance)
    branch(new_branch)
    switch_branch(branch)
    merge(branch1, branch2)

    _compose_deltas
    _invert_delta
    _merge_into_current_branch
    _create_identity_delta
    _compose_delta_path
    """

    def __init__(self, init_branch="master"):
        """Initialize revision object."""
        self._current_branch = init_branch
        self._deltas = {}

        # Create initial commit
        time, commit_id = _generate_new_commit_meta_data()
        self._heads = {}
        self._heads[init_branch] = commit_id
        self._revision_graph = nx.DiGraph()
        self._revision_graph.add_node(
            commit_id,
            branch=self._current_branch,
            message="Initial commit",
            time=time
        )

    @abstractmethod
    def _compose_deltas(self, delta1, delta2):
        """Abstract method for composing deltas."""
        pass

    @staticmethod
    @abstractmethod
    def _invert_delta(self, delta1):
        """Abstract method for inverting deltas."""
        pass

    @staticmethod
    @abstractmethod
    def _merge_into_current_branch(self, delta):
        """Abstract method for merging a branch into the current one."""
        pass

    @abstractmethod
    def _create_identity_delta(self):
        """Abstract method for creating an identity-delta."""
        pass

    def _compose_delta_path(self, path):
        # print(path)
        if len(path) > 1:
            result_delta = self._revision_graph.adj[
                path[0]][path[1]]["delta"]
            previous_commit = path[1]
            # print("\t\t--> subdelta")
            # print("\t", result_delta["rule"])
            for current_commit in path[2:]:
                result_delta = self._compose_deltas(
                    result_delta,
                    self._revision_graph.adj[
                        previous_commit][current_commit]["delta"])
                # print("\t\t--> subdelta")
                # print("\t", self._revision_graph.adj[
                #    previous_commit][current_commit]["delta"]["rule"])
                previous_commit = current_commit
            return result_delta
        else:
            return self._create_identity_delta()

    def branches(self):
        """Return list of branches."""
        return list(self._heads.keys())

    def current_branch(self):
        """Return the name of the current branch."""
        return self._current_branch

    def commit(self, delta, message=None, previous_commit=None):
        """Add a commit."""
        time, commit_id = _generate_new_commit_meta_data()

        if previous_commit is None:
            previous_commit = self._heads[self._current_branch]

        # Update heads and revision graph
        self._heads[self._current_branch] = commit_id
        self._revision_graph.add_node(
            commit_id,
            branch=self._current_branch,
            time=time,
            message=message if message is not None else "")
        self._revision_graph.add_edge(
            previous_commit, commit_id, delta=delta)

        # Update deltas
        for branch, branch_delta in self._deltas.items():
            self._deltas[branch] = self._compose_deltas(
                self._invert_delta(delta), branch_delta)
            print(self._deltas[branch]["rule"])
            self._refine_delta(self._deltas[branch])
            print(self._deltas[branch]["rule"])

        return commit_id

    def switch_branch(self, branch):
        """Switch branches."""
        if branch not in self.branches():
            raise RevisionError(
                "Branch '{}' does not exist".format(branch))
        if branch == self._current_branch:
            warnings.warn("Already in branch '{}'".format(branch), RevisionWarning)

        # Set as the current branch
        previous_branch = self._current_branch
        self._current_branch = branch

        # Apply delta to the versioned object
        delta = self._deltas[branch]
        self._apply_delta(delta)
        self._deltas[previous_branch] = self._invert_delta(delta)

        # Recompute deltas
        for name, another_delta in self._deltas.items():
            if name != previous_branch:
                self._deltas[name] = self._compose_deltas(
                    self._deltas[previous_branch],
                    another_delta
                )
        del self._deltas[self._current_branch]

    def branch(self, new_branch, message=None):
        """Create a new branch with identity commit."""
        if new_branch in self.branches():
            raise RevisionError(
                "Branch '{}' already exists".format(new_branch))

        if message is None:
            message = "Created branch '{}'".format(new_branch)

        # Set this as a current branch
        previous_branch = self._current_branch
        previous_commit = self._heads[self._current_branch]
        self._current_branch = new_branch

        identity_delta = self._create_identity_delta()

        # Add a new delta
        self._deltas[previous_branch] = identity_delta

        # Create a new identity commit
        commit_id = self.commit(
            identity_delta,
            message=message,
            previous_commit=previous_commit)
        self._heads[self._current_branch] = commit_id
        return commit_id

    def merge_with(self, branch, message=None):
        """Merge the current branch with the specified one."""
        if branch not in self.branches():
            raise RevisionError(
                "Branch '{}' does not exist".format(branch))

        if message is None:
            message = "Merged branch '{}' into '{}'".format(
                branch, self._current_branch)

        delta = self._deltas[branch]
        delta_to_current, delta_to_branch = self._merge_into_current_branch(
            delta)

        commit_id = self.commit(delta_to_current, message=message)

        self._revision_graph.add_edge(
            self._heads[branch], commit_id,
            delta=delta_to_branch)

        del self._heads[branch]
        del self._deltas[branch]
        return commit_id

    def rollback(self, rollback_commit, message=None):
        """Rollback the current branch to a specific commit."""
        if rollback_commit not in self._revision_graph.nodes():
            raise RevisionError(
                "Commit '{}' does not exist in the revision graph".format(
                    rollback_commit))

        # Find paths from the last commit of the current branch
        # to the commit with id 'rollback_commit'
        try:
            shortest_path = list(nx.shortest_path(
                self._revision_graph, rollback_commit, self._heads[self._current_branch]))
        except nx.NetworkXNoPath:
            raise RevisionError(
                "Branch '{}' does not contain a path to the commit '{}'".format(
                    self._current_branch, rollback_commit))

        if message is None:
            message = "Rollback to commit '{}'".format(rollback_commit)

        # Generate a big rollback commit
        rollback_delta = self._invert_delta(
            self._compose_delta_path(shortest_path))
        self._refine_delta(rollback_delta)

        # Apply the rollback commit
        self._apply_delta(rollback_delta)

        print("-> Rollback rule:")
        print(rollback_delta["rule"])

        # Compute all paths from every head to the commit
        head_paths = {}
        for h in self._heads.values():
            head_paths[h] = list(nx.all_simple_paths(
                self._revision_graph, rollback_commit, h))

        # Compute new head commits (commits whose successors
        # are merge commits to be removed)
        new_heads = {}
        removed_commits = set(
            [n for pp in head_paths.values() for p in pp for n in p if n != rollback_commit])
        for n in self._revision_graph.nodes():
            for s in self._revision_graph.successors(n):
                if n not in removed_commits and s in removed_commits:
                    new_heads[self._revision_graph.node[n]["branch"]] = (n, s)

        # Recompute deltas
        new_current_branch = self._revision_graph.node[rollback_commit]["branch"]
        self._current_branch = new_current_branch
        self._heads[self._current_branch] = rollback_commit

        bfs_from_commit = nx.bfs_tree(
            self._revision_graph, rollback_commit, reverse=True)

        # Update deltas of the preserved heads
        for head, commit in self._heads.items():
            if head != self._current_branch:
                # Find the last branching point
                branching = None
                for n in bfs_from_commit.nodes():
                    successors = self._revision_graph.successors(n)
                    for s in successors:
                        if self._revision_graph.node[s]["branch"] == head:
                            branching = n
                if branching:
                    branching_to_head = nx.shortest_path(self._revision_graph, branching, commit)

                branching_to_rollback = nx.shortest_path(
                    self._revision_graph, branching, rollback_commit)

                self._deltas[head] = self._compose_deltas(
                    self._invert_delta(
                        self._compose_delta_path(branching_to_rollback)),
                    self._compose_delta_path(branching_to_head)
                )
                self._refine_delta(self._deltas[head])
                # self._deltas[head] = self._compose_deltas(
                #     self._invert_delta(rollback_delta),
                #     self._deltas[head])

        # Compute deltas of the new heads
        for branch, (head_commit, merge_commit)in new_heads.items():
            path_to_merge = nx.shortest_path(
                self._revision_graph, rollback_commit, merge_commit)
            delta_to_merge = self._compose_delta_path(path_to_merge)
            head_to_merge = self._revision_graph.adj[head_commit][merge_commit]["delta"]
            self._deltas[branch] = self._compose_deltas(
                delta_to_merge,
                self._invert_delta(head_to_merge))
            self._refine_delta(self._deltas[branch])
            self._heads[branch] = head_commit
            print("Created the new head for '{}'".format(branch))

        # All paths to the heads originating from the commit to
        # which we rollaback are removed
        for c in removed_commits:
            if c != rollback_commit:
                self._revision_graph.remove_node(c)
                if c in self._heads.values():
                    for h in keys_by_value(self._heads, c):
                        print("Removed a head for '{}'".format(h))
                        del self._heads[h]


class VersionedGraph(Versioning):
    """Class for versioned ."""

    def __init__(self, graph, init_branch="master"):
        """Initialize versioned graph object."""
        self.graph = graph
        super().__init__(init_branch)

    def _refine_delta(self, delta):
        lhs = delta["rule"].refine(self.graph, delta["lhs_instance"])
        delta["lhs_instance"] = lhs
        for n in delta["rule"].rhs.nodes():
            if n not in delta["rhs_instance"].keys():
                delta["rhs_instance"][n] = lhs[
                    delta["rule"].p_lhs[keys_by_value(delta["rule"].p_rhs, n)[0]]]

    def _compose_deltas(self, delta1, delta2):
        """Computing composition of two deltas."""
        rule, lhs, rhs = compose_rules(
            delta1["rule"],
            delta1["lhs_instance"],
            delta1["rhs_instance"],
            delta2["rule"],
            delta2["lhs_instance"],
            delta2["rhs_instance"])

        return {
            "rule": rule,
            "lhs_instance": lhs,
            "rhs_instance": rhs
        }

    @staticmethod
    def _invert_delta(delta):
        """Reverse the direction of delta."""
        return {
            "rule": delta["rule"].get_inverted_rule(),
            "lhs_instance": delta["rhs_instance"],
            "rhs_instance": delta["lhs_instance"]
        }

    @staticmethod
    def _create_identity_delta():
        """Create an identity-delta."""
        rule = Rule.identity_rule()
        identity_delta = {
            "rule": rule,
            "lhs_instance": {},
            "rhs_instance": {}
        }
        return identity_delta

    def _apply_delta(self, delta, relabel=True):
        """Apply delta to the current graph version."""
        _, rhs_instance = delta["rule"].apply_to(
            self.graph, delta["lhs_instance"], inplace=True)

        if relabel:
            # Relabel nodes to correspond to the stored rhs
            new_labels = {
                v: delta["rhs_instance"][k]
                for k, v in rhs_instance.items()
            }
            second_round = []
            for k, v in new_labels.items():
                if k != v:
                    try:
                        relabel_node(self.graph, k, v)
                    except:
                        second_round.append(k)
            for k in second_round:
                if k != new_labels[k]:
                    try:
                        relabel_node(self.graph, k, new_labels[k])
                    except:
                        pass

            rhs_instance = {
                k: new_labels[v]
                for k, v in rhs_instance.items()
            }
        return rhs_instance

    def _merge_into_current_branch(self, delta):
        """Merge branch with delta into the current branch."""

        current_to_merged_rule, other_to_merged_rule =\
            _create_merging_rule(
                delta["rule"], delta["lhs_instance"], delta["rhs_instance"])

        _, rhs_instance = current_to_merged_rule.apply_to(
            self.graph, delta["lhs_instance"], inplace=True)

        current_to_merged_delta = {
            "rule": current_to_merged_rule,
            "lhs_instance": delta["lhs_instance"],
            "rhs_instance": rhs_instance
        }

        other_to_merged_delta = {
            "rule": other_to_merged_rule,
            "lhs_instance": delta["rhs_instance"],
            "rhs_instance": rhs_instance
        }

        return current_to_merged_delta, other_to_merged_delta

    def rewrite(self, rule, instance=None, message=None):
        """Rewrite the versioned graph and commit."""
        # Refine a rule to be side-effect free
        refined_instance = rule.refine(self.graph, instance)
        _, rhs_instance = rule.apply_to(
            self.graph, refined_instance, inplace=True)

        commit_id = self.commit({
            "rule": rule,
            "lhs_instance": refined_instance,
            "rhs_instance": rhs_instance
        }, message=message)
        return rhs_instance, commit_id


# class VersionedHierarchy(Versioning);
#     pass