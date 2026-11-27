"""The existing RPE (mu+lambda) selector, parameterized by domain callbacks.

Ranking, feasibility and the meaning of a genome belong to each domain. This
module deliberately has no modern-poetry metrics or language-model calls.
"""


def select_survivors(pool, *, size, rank_key, genome, similarity, max_similarity=.88):
    if type(size) is not int or size < 1 or not 0 <= max_similarity <= 1:
        raise ValueError('invalid population configuration')
    ranked = sorted(pool, key=rank_key, reverse=True)
    survivors, seen = [], set()
    for candidate in ranked:
        text = genome(candidate)
        if not text or text in seen:
            continue
        if any(similarity(text, genome(s)) >= max_similarity for s in survivors):
            continue
        seen.add(text)
        survivors.append(candidate)
        if len(survivors) >= size:
            break
    if len(survivors) < size:
        for candidate in ranked:
            text = genome(candidate)
            if text in seen:
                continue
            seen.add(text)
            survivors.append(candidate)
            if len(survivors) >= size:
                break
    if len(survivors) < size:
        for candidate in ranked:
            if candidate not in survivors:
                survivors.append(candidate)
            if len(survivors) >= size:
                break
    return survivors


def crossover_pairs(parents, *, count, rank_key, genome, similarity, eligible=lambda _: True):
    ranked = [p for p in sorted(parents, key=rank_key, reverse=True) if eligible(p)]
    if len(ranked) < 2 or count <= 0:
        return []
    pairs = []
    for i in range(len(ranked)):
        for j in range(i + 1, len(ranked)):
            if similarity(genome(ranked[i]), genome(ranked[j])) < .92:
                pairs.append((ranked[i], ranked[j]))
            if len(pairs) >= count:
                return pairs
    while len(pairs) < count:
        pairs.append((ranked[0], ranked[min(len(ranked) - 1, len(pairs) + 1)]))
    return pairs[:count]
