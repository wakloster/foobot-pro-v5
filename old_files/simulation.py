import numpy as np
from config import SIMULATIONS
def monte_carlo(lh, la):
    resultados = []
    for _ in range(SIMULATIONS):
        gh = np.random.poisson(lh)
        ga = np.random.poisson(la)
        resultados.append((gh, ga))
    return resultados