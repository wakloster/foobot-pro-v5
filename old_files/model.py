import math
def poisson(lam, k):
    return (math.exp(-lam) * lam**k) / math.factorial(k)