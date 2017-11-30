"""A collection of (internal usage) utils for rule type checking."""
import networkx as nx
from networkx.exception import NetworkXNoPath

from regraph.category_op import check_homomorphism
from regraph.exceptions import RewritingError, ReGraphError
from regraph.utils import keys_by_value, format_typing


def _autocomplete_typing(hierarchy, graph_id, instance,
                         lhs_typing, rhs_typing_rel, p_lhs, p_rhs):
    print("Initial rhs typing: ", rhs_typing_rel)
    if len(hierarchy.successors(graph_id)) > 0:
        if lhs_typing is None:
            new_lhs_typing = dict()
        else:
            new_lhs_typing = format_typing(lhs_typing)
        if rhs_typing_rel is None:
            new_rhs_typing_rel = dict()
        else:
            new_rhs_typing_rel = format_typing(rhs_typing_rel)
            for g, typing_rel in new_rhs_typing_rel.items():
                for key, values in typing_rel.items():
                    value_set = set()
                    if type(values) == str:
                        value_set.add(values)
                    else:
                        try:
                            for v in values:
                                value_set.add(v)
                        except TypeError:
                            value_set.add(v)
                    new_rhs_typing_rel[g][key] = value_set

        ancestors = hierarchy.get_ancestors(graph_id)
        for anc, anc_typing in ancestors.items():
            if anc not in new_rhs_typing_rel.keys():
                new_rhs_typing_rel[anc] = dict()

        merged_nodes = set()
        for r_node in p_rhs.values():
            p_nodes = keys_by_value(p_rhs, r_node)
            if len(p_nodes) > 1:
                merged_nodes.add(r_node)

        for typing_graph in hierarchy.successors(graph_id):
            typing = hierarchy.edge[graph_id][typing_graph].mapping
            # Autocomplete lhs and rhs typings
            # by immediate successors induced by an instance
            for (source, target) in instance.items():
                if typing_graph not in new_lhs_typing.keys():
                    new_lhs_typing[typing_graph] = dict()
                if source not in new_lhs_typing[typing_graph].keys():
                    if target in typing.keys():
                        new_lhs_typing[typing_graph][source] = typing[target]
            for (p_node, l_node) in p_lhs.items():
                if l_node in new_lhs_typing[typing_graph].keys():
                    if p_rhs[p_node] not in new_rhs_typing_rel[typing_graph].keys():
                        new_rhs_typing_rel[typing_graph][p_rhs[p_node]] = set()

                    new_rhs_typing_rel[typing_graph][p_rhs[p_node]].add(
                        new_lhs_typing[typing_graph][l_node])

        # Second step of autocompletion of rhs typing
        for graph, typing in new_rhs_typing_rel.items():
            print("Autocompleting ancestors of: ", graph)
            ancestors = hierarchy.get_ancestors(graph)
            for ancestor, ancestor_typing in ancestors.items():
                print("\tAncestor: ", ancestor, ancestor_typing)
                dif = set(typing.keys()) -\
                    set(new_rhs_typing_rel[ancestor].keys())
                print("\tTyped here, but not ancestor: ", dif)
                for node in dif:
                    type_set = set()
                    for el in new_rhs_typing_rel[graph][node]:
                        type_set.add(ancestor_typing[el])
                    new_rhs_typing_rel[ancestor][node] = type_set
        return (new_lhs_typing, new_rhs_typing_rel)
    else:
        return (None, None)


def _check_lhs_rhs_consistency(hierarchy, graph_id, rule, instance,
                               lhs_typing, rhs_typing):
    for typing_graph, typing in lhs_typing.items():
        typing_graph_ancestors = hierarchy.get_ancestors(typing_graph)
        for ancestor, ancestor_typing in typing_graph_ancestors.items():
            if ancestor in rhs_typing.keys():
                for p_node in rule.p.nodes():
                    if rule.p_rhs[p_node] in rhs_typing[ancestor] and\
                        len(rhs_typing[ancestor][rule.p_rhs[p_node]]) == 1 and\
                        ancestor_typing[typing[rule.p_lhs[p_node]]] not in\
                            rhs_typing[ancestor][rule.p_rhs[p_node]]:
                        raise RewritingError(
                            "Inconsistent typing of the rule: "
                            "node '%s' from the preserved part is typed "
                            "by a graph '%s' as "
                            "'%s' from the lhs and as a '%s' from the rhs." %
                            (p_node, ancestor,
                             ancestor_typing[typing[rule.p_lhs[p_node]]],
                             rhs_typing[ancestor][rule.p_rhs[p_node]])
                        )


def _check_self_consistency(hierarchy, typing):
    for typing_graph, mapping in typing.items():
        ancestors = hierarchy.get_ancestors(typing_graph)
        for anc, anc_typing in ancestors.items():
            if anc in typing.keys():
                for key, value in mapping.items():
                    if key in typing[anc].keys():
                        if type(value) == str:
                            if value in anc_typing.keys() and\
                               anc_typing[value] != typing[anc][key]:
                                raise ReGraphError(
                                    "Node '%s' is typed as "
                                    "'%s' and '%s' in the graph '%s'" %
                                    (key, anc_typing[value], typing[anc][key],
                                        anc)
                                )
                        else:
                            try:
                                for val in value:
                                    if val in anc_typing.keys() and\
                                       anc_typing[val] not in typing[anc][key]:
                                        raise ReGraphError(
                                            "Node '%s' is typed as "
                                            "'%s' and '%s' in the graph '%s'" %
                                            (key, anc_typing[val], typing[anc][key],
                                                anc)
                                        )
                            except TypeError as e:
                                if value in anc_typing.keys() and\
                                   anc_typing[value] != typing[anc][key]:
                                    raise ReGraphError(
                                        "Node '%s' is typed as "
                                        "'%s' and '%s' in the graph '%s'" %
                                        (key, anc_typing[value], typing[anc][key],
                                            anc)
                                    )


def _check_totality(hierarchy, graph_id, rule, instance,
                    lhs_typing, rhs_typing):
    """"Check that everything is typed at the end of the rewriting."""
    for node in rule.rhs.nodes():
        p_nodes = keys_by_value(rule.p_rhs, node)
        for typing_graph in hierarchy.successors(graph_id):
            typing = hierarchy.edge[graph_id][typing_graph].mapping
            # Totality can be broken in two cases
            if len(p_nodes) > 1:
                # node will be merged
                all_untyped = True
                for p_node in p_nodes:
                    if instance[rule.p_lhs[p_node]] in typing.keys():
                        all_untyped = False
                        break
                if all_untyped:
                    continue

            if typing_graph in rhs_typing.keys() and\
               node in rhs_typing[typing_graph].keys():
                continue
            else:
                visited_successors = set()
                resolved_successors = set()
                successors_to_visit = set(
                    hierarchy.successors(typing_graph)
                )
                while len(successors_to_visit) > 0:
                    for suc in successors_to_visit:
                        visited_successors.add(suc)
                        if suc in rhs_typing.keys() and\
                           node in rhs_typing[suc].keys():
                            resolved_successors.add(suc)

                    new_successors_to_visit = set()
                    for suc in successors_to_visit:
                        new_successors_to_visit.update(
                            [s for s in hierarchy.successors(suc)
                             if s not in visited_successors]
                        )
                    successors_to_visit = new_successors_to_visit

                if len(visited_successors - resolved_successors) > 0:
                    raise RewritingError(
                        "Rewriting parameter `total` is set to True, "
                        "typing of the node `%s` "
                        "in rhs is required (typing by the following "
                        "graphs stays unresolved: %s)!" %
                        (node,
                         ", ".join(visited_successors - resolved_successors))
                    )


def _check_instance(hierarchy, graph_id, pattern, instance, pattern_typing):
    check_homomorphism(
        pattern,
        hierarchy.node[graph_id].graph,
        instance,
        total=True
    )
    # check that instance typing and lhs typing coincide
    for node in pattern.nodes():
        if pattern_typing:
            for typing_graph, typing in pattern_typing.items():
                try:
                    instance_typing = hierarchy.compose_path_typing(
                        nx.shortest_path(hierarchy, graph_id, typing_graph)
                    )
                    if node in pattern_typing.keys() and\
                       instance[node] in instance_typing.keys():
                        if typing[node] != instance_typing[instance[node]]:
                            raise RewritingError(
                                "Typing of the instance of LHS does not " +
                                " coincide with typing of LHS!"
                            )
                except NetworkXNoPath:
                    raise ReGraphError(
                        "Graph '%s' is not typed by '%s' specified "
                        "as a typing graph of the lhs of the rule." %
                        (graph_id, typing_graph)
                    )
    return
