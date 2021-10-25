import os
from re import L
import pfrl
import torch
import scipy
import numpy as np
from tqdm import tqdm
import matplotlib.pyplot as plt
from treelib import Tree, Node
from pfrl.wrappers import atari_wrappers
from hrl.agent.rainbow.rainbow import Rainbow


class SkillTree(object):
    def __init__(self, options):
        self._tree = Tree()
        self.options = options

        if len(options) > 0:
            [self.add_node(option) for option in options]

    def add_node(self, option):
        if option.name not in self._tree:
            print(f"Adding {option} to the skill-tree")
            self.options.append(option)
            parent = option.parent.name if option.parent is not None else None
            self._tree.create_node(tag=option.name, identifier=option.name, data=option, parent=parent)

    def get_option(self, option_name):
        if option_name in self._tree.nodes:
            node = self._tree.nodes[option_name]
            return node.data

    def get_depth(self, option):
        return self._tree.depth(option.name)

    def get_children(self, option):
        return self._tree.children(option.name)

    def traverse(self):
        """ Breadth first search traversal of the skill-tree. """
        return list(self._tree.expand_tree(mode=self._tree.WIDTH))

    def show(self):
        """ Visualize the graph by printing it to the terminal. """
        self._tree.show()


def make_meshgrid(x, y, h=1.):
    x_min, x_max = x.min() - 1, x.max() + 1
    y_min, y_max = y.min() - 1, y.max() + 1
    xx, yy = np.meshgrid(np.arange(x_min, x_max, h),
                         np.arange(y_min, y_max, h))
    return xx, yy

def get_grid_states(low, high, res):
    ss = []
    for x in np.arange(low[0], high[0]+res, res):
        for y in np.arange(low[1], high[1]+res, res):
            pos = np.array((x, y))
            ss.append(pos)
    return ss


def get_initiation_set_values(option, low, high, res):
    values = []
    for x in np.arange(low[0], high[0]+res, res):
        for y in np.arange(low[1], high[1]+res, res):
            pos = np.array((x, y))
            init = option.is_init_true(pos)
            values.append(init)
    return values

def plot_one_class_initiation_classifier(option):

    colors = ["blue", "yellow", "green", "red", "cyan", "brown"]

    X = option.initiation_classifier.construct_feature_matrix(option.initiation_classifier.positive_examples)
    X0, X1 = X[:, 0], X[:, 1]
    xx, yy = make_meshgrid(X0, X1)
    Z1 = option.initiation_classifier.pessimistic_classifier.decision_function(np.c_[xx.ravel(), yy.ravel()])
    Z1 = Z1.reshape(xx.shape)

    color = colors[option.option_idx % len(colors)]
    plt.contour(xx, yy, Z1, levels=[0], linewidths=2, colors=[color])

def plot_two_class_classifier(option, episode, experiment_name, plot_examples=True, seed=0):
    low = 0, 140
    high = 150, 250
    states = get_grid_states(low, high, res=10)
    values = get_initiation_set_values(option, low, high, res=10)

    x = np.array([state[0] for state in states])
    y = np.array([state[1] for state in states])
    xi, yi = np.linspace(x.min(), x.max(), 100), np.linspace(y.min(), y.max(), 100)
    xx, yy = np.meshgrid(xi, yi)
    rbf = scipy.interpolate.Rbf(x, y, values, function="linear")
    zz = rbf(xx, yy)
    plt.imshow(zz, vmin=min(values), vmax=max(values), extent=[x.min(), x.max(), y.min(), y.max()], origin="lower", alpha=0.6, cmap=plt.cm.coolwarm)
    plt.colorbar()

    # Plot trajectories
    positive_examples = option.initiation_classifier.construct_feature_matrix(option.initiation_classifier.positive_examples)
    negative_examples = option.initiation_classifier.construct_feature_matrix(option.initiation_classifier.negative_examples)

    if positive_examples.shape[0] > 0 and plot_examples:
        plt.scatter(positive_examples[:, 0], positive_examples[:, 1], label="positive", c="black", alpha=0.3, s=10)

    if negative_examples.shape[0] > 0 and plot_examples:
        plt.scatter(negative_examples[:, 0], negative_examples[:, 1], label="negative", c="lime", alpha=1.0, s=10)

    if option.initiation_classifier.pessimistic_classifier is not None:
        plot_one_class_initiation_classifier(option)

    # background_image = imageio.imread("four_room_domain.png")
    # plt.imshow(background_image, zorder=0, alpha=0.5, extent=[-2.5, 10., -2.5, 10.])

    plt.title(f"{option.name} Initiation Set")
    plt.savefig(f"plots/{experiment_name}/{seed}/initiation_set_plots/{option.name}_{episode}_initiation_classifier.png")
    plt.close()


def make_chunked_goal_conditioned_value_function_plot(solver,
                                                      goal, episode, seed,
                                                      experiment_name, chunk_size=1000, option_idx=None):
    assert isinstance(solver, Rainbow)

    replay_buffer = solver.rbuf

    def _get_states():
        states = []
        positions = []
        memory = replay_buffer.memory.data
        for n_transitions in memory:
            transition = n_transitions[-1]
            states.append(transition["next_state"])
            positions.append(transition["position"])
        return states, positions

    def cat(s, g):
        assert isinstance(s, atari_wrappers.LazyFrames)
        g = g._frames[-1] if isinstance(g, atari_wrappers.LazyFrames) else g
        return atari_wrappers.LazyFrames(list(s._frames)[:4] + [g], stack_axis=0)

    def _get_gc_states():
        states, positions = _get_states()
        return [cat(s, goal) for s in states], positions

    # Take out the original goal and append the new goal
    states, positions = _get_gc_states()

    # Chunk up the inputs so as to conserve GPU memory
    num_chunks = int(np.ceil(len(states) / chunk_size))

    if num_chunks == 0:
        return 0.

    state_chunks = np.array_split(states, num_chunks, axis=0)
    values = np.zeros((len(states),))
    current_idx = 0

    for state_chunk in tqdm(state_chunks, desc="Making VF plot"):
        current_chunk_size = len(state_chunk)
        values[current_idx:current_idx + current_chunk_size] = solver.value_function(state_chunk)
        current_idx += current_chunk_size

    plt.scatter(positions[:, 0], positions[:, 1], c=values)
    plt.colorbar()
    plt.title(f"VF Targeting {np.round(goal, 2)}")
    plt.savefig(f"plots/{experiment_name}/{seed}/value_function_episode_{episode}_option_{option_idx}.png")
    plt.close()

    return values.max()
