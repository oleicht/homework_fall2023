1) See hw1 if you'd like to see installation instructions. You do NOT have to redo them.
2) See the PDF for the rest of the instructions.


## Finetuning performance
The PDF says that a score of at least -20 is attainable for PointmassHard-v0. At the moment I don't get close: the best trajectories across different algorithms are around -30. I tried the reward transformation trick: r = (r+1)*100, this helps speed up training a lot but doesn't improve the best trajectories. Besides a bug in the code, my main suspicion is that I use the wrong evaluation protocol. Maybe I should start evaluation trajectories at random points and not the same point (that is pretty far away from the goal).