import numpy as np
import pandas as pd
import requests 
import xlwings as xw
from scipy.optimize import minimize_scalar
import matplotlib.pyplot as plt

df = pd.read_excel(r"C:\Users\Administrator\Desktop\orchestra.xlsx", sheet_name="SKHynix")
df = df.rename(columns={
    "OpenPrice": "Open",
    "ClosePrice": "Close",
    "HighPrice": "High",
    "LowPrice": "Low",
    "volume": "volume"
})