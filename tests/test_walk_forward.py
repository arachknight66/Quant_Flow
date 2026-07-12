import pytest
import numpy as np
import pandas as pd
from ml.backtesting.engine import WalkForwardSplitter

def test_walk_forward_splitter():
    # 500 rows
    X = pd.DataFrame(np.random.randn(500, 3))
    
    n_splits = 5
    test_size = 50
    gap = 10
    min_train_size = 150
    
    splitter = WalkForwardSplitter(n_splits=n_splits, test_size=test_size, gap=gap, min_train_size=min_train_size)
    splits = list(splitter.split(X))
    
    # Check that we got splits
    assert len(splits) > 0
    
    last_test_start = -1
    for i, (train_idx, test_idx) in enumerate(splits):
        assert len(train_idx) >= min_train_size
        assert len(test_idx) == test_size
        
        # 1. All train indices must be strictly less than test indices
        assert train_idx[-1] < test_idx[0]
        
        # 2. Gap is respected (train_end to test_start)
        assert test_idx[0] - train_idx[-1] == gap + 1
        
        # 3. Chronological fold order: test starts must be strictly increasing
        assert test_idx[0] > last_test_start
        last_test_start = test_idx[0]
        
        # 4. Disjoint sets
        train_set = set(train_idx)
        test_set = set(test_idx)
        assert train_set.isdisjoint(test_set)
