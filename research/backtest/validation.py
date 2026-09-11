import pandas as pd

def walk_forward_split(df: pd.DataFrame, train_ratio: float = 0.7):
    split_idx = int(len(df) * train_ratio)
    train = df.iloc[:split_idx].reset_index(drop=True)
    test = df.iloc[split_idx:].reset_index(drop=True)
    return train, test