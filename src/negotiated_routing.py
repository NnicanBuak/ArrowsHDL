"""Negotiated routing: history penalties and partial bus repair."""
from collections import defaultdict, deque
from heapq import heappop, heappush
import math
from compact_layout import Router, manhattan
from arrowasm import MapError, validate_cell

class CongestionRouting:
    def ripup_conflicts(self,net,path):
        """Preserve unaffected branches of a bus when repairing one collision."""
        cut={p for p in path if self.owners.get(p)==net and p not in self.fixed_cells}
        points={p for p in self.cells if self.owners.get(p)==net}
        # A flexible OR/BUF root is owned by "gate:<id>", not by its
        # output net. Its removed branch must also disappear from outs.
        root=self.roots[net]
        for p in points|{root}:
            if p in self.outs:self.outs[p].difference_update(cut)
        reachable=self.tree(net)
        removed={p for p in points if p not in self.fixed_cells and (p in cut or p not in reachable)}
        while removed:
            for p in removed:
                self.cells.pop(p,None);self.owners.pop(p,None);self.outs.pop(p,None)
            for p in (points-removed)|{root}:
                if p in self.outs:self.outs[p].difference_update(removed)
            points-=removed
            removed={p for p in points if p not in self.fixed_cells and not self.outs.get(p)}

    def route_phase(self,targets):
        budget_scale=getattr(self,'routing_budget_scale',1)
        if type(budget_scale) is not int or not 1<=budget_scale<=16:
            raise MapError('Routing budget scale must be an integer from 1 to 16')
        self.routing_history = {}
        incremental=set()
        order=sorted((net for net,sinks in targets.items() if sinks),key=lambda net:(-len(targets[net]),net))
        initial=getattr(self,'initial_routing_nets',None)
        if initial is not None:order=[net for net in order if net in initial]
        mode=getattr(self,'routing_order','fanout')
        if mode in ('short','long'):
            sign=1 if mode=='short' else -1
            order.sort(key=lambda net:(sign*sum(manhattan(self.roots[net],p) for p in set(targets[net])),net))
        queue, attempts = deque(order), 0
        net_attempts=defaultdict(int)
        conflicts=defaultdict(int);last_goal={}
        def fail(message,net,goal=None):
            common=sorted(conflicts.items(),key=lambda e:-e[1])[:5]
            message+=f'; goal={goal or last_goal.get(net)}; conflicts={common}'
            error=MapError(message);error.net=net;error.goal=goal
            raise error
        while queue:
            net = queue.popleft()
            attempts += 1
            net_attempts[net] += 1
            # A few conflicting nets must not consume the entire graph's budget
            # by repeatedly tearing down each other's identical routes.
            limit=budget_scale*max(30,len(set(targets[net]))*12)
            if net_attempts[net] > limit:
                fail(f"Цепь {net} повторно конфликтует: исчерпан лимит {limit} перестроений",net)
            if attempts > budget_scale*max(40, len(order)*20):
                fail("Исчерпан бюджет перестройки проводов",net)
            if attempts%400==0:print(f'Routing progress: {attempts} repairs, {len(queue)} nets pending, {len(self.cells)} arrows',flush=True)
            # A retained trunk can force two nets to repair the same crossing
            # forever. Periodically release the whole trunk so congestion
            # history can choose a different topology, not just another leaf.
            if mode=='full' or net not in incremental or net_attempts[net]%3==0:self.clear_net(net)
            incremental.discard(net)
            tree=self.tree(net)
            pending=set(targets[net])-tree
            while pending:
                goal = min(pending, key=lambda p: (min(manhattan(p, start) for start in tree), p))
                last_goal[net]=goal
                path = None
                for margin in (3, 8, 16, 32):
                    path = self.path(tree, goal, margin)
                    if path:
                        break
                if path is None:
                    path = self.path(tree,goal,8,soft=True)
                    if path is None:
                        fail(f"Не удалось проложить компактную цепь {net}",net,goal)
                    blockers = sorted({self.owners[p] for p in path if p in self.cells and p not in self.fixed_cells and self.owners[p] != net})
                    for point in path:
                        if point in self.cells and point not in self.fixed_cells and self.owners.get(point) != net:
                            self.routing_history[point] = self.routing_history.get(point, 0) + 5
                    for blocker in blockers:
                        conflicts[(net,blocker)]+=1
                        self.ripup_conflicts(blocker,path)
                        incremental.add(blocker)
                        if blocker not in queue:
                            queue.append(blocker)
                        self.ripups += 1
                    path = self.path(tree,goal,32)
                    if path is None:
                        fail(f"Не удалось перестроить цепь {net}",net,goal)
                for key in path[1:-1]:
                    self.add(key, net)
                for key, target in zip(path, path[1:]):
                    self.outs[key].add(target)
                tree.update(path)
                pending.remove(goal)

    def route(self, order=None):
        if self.routing_strategy == 'core_io':
            return Router.route(self, order)
        self.io_conflict_fallback = True
        self.route_phase(self.sinks)
        return self.finish()


class NegotiatedRouter(CongestionRouting, Router):
    """Congestion-history routing for arbitrary fixed physical interfaces."""
    routing_strategy = 'all'
    routing_order = 'fanout'
