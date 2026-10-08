"""Training data and the operators that learn from it.

A service becomes a bundle in runs/<key>/: the recording, the slide deck, the
bulletin, and the marks a person made while listening (marks.py). Anything that
decides when the deck should move is an operator (operator.py); the runner
replays a bundle to an operator strictly in time order (runner.py), and the
scorer compares what it did with the marks (score.py).
"""
