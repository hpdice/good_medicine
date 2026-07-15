"""
약물-약물 상호작용(DDI) 예측 모델 학습 + 평가

배경
----
DUR 병용금기 데이터(drug_interactions, 324,321쌍)는 132개의 성분/계열 단위
기전(mechanism) 규칙이 약품 조합으로 전개된 결과다. 전체 35,299개 약품 중
DUR에 상호작용 기록이 하나라도 있는 약품은 8,227개(약 23%)뿐이며, 나머지
약 77%는 "안전이 검증된 것"이 아니라 "DUR이 아직 다루지 않은 것"이다.
이 스크립트는 알려진 병용금기 패턴(계열, 성분, 그래프 구조)으로부터
DUR에 없는 약품 쌍의 위험도를 추정하는 모델을 학습하고 평가한다.

중요한 한계
----------
DUR에 없는 쌍이 "안전"이라는 보장은 없다 (단지 미검증일 뿐). 따라서 음성
라벨은 무작위 샘플링으로 근사한 것이며, 여기서 보고하는 정확도는 실제
임상적 안전성 보장이 아니라 "DUR 패턴을 얼마나 잘 재현하는가"에 대한
지표다. API/앱에 노출하기 전 별도의 제품 결정이 필요하다.

사용법
------
    poetry install --with ml
    poetry run python ml/train_ddi_model.py
"""
from __future__ import annotations

import asyncio
import json
import random
import time
from dataclasses import dataclass

import joblib
import numpy as np
from scipy import sparse
from sklearn.decomposition import TruncatedSVD
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import average_precision_score, roc_auc_score

RANDOM_SEED = 42
EMBEDDING_DIM = 64
TEST_EDGE_FRACTION = 0.15
NEGATIVE_TO_POSITIVE_RATIO = 1  # 평가용 균형 테스트셋 (1:1)
ARTIFACT_DIR = "ml/artifacts"

random.seed(RANDOM_SEED)
np.random.seed(RANDOM_SEED)


@dataclass
class DrugRecord:
    id: str
    class_name: str | None
    dur_codes: frozenset[str]


async def _load_data():
    from app.db.session import AsyncSessionLocal
    from sqlalchemy import select
    from app.models.drug import Drug
    from app.models.drug_interaction import DrugInteraction

    async with AsyncSessionLocal() as db:
        drug_rows = (await db.execute(
            select(Drug.id, Drug.class_name, Drug.ingr_name)
        )).all()
        pair_rows = (await db.execute(
            select(DrugInteraction.drug1_id, DrugInteraction.drug2_id)
            .where(DrugInteraction.interaction_type == "contraindicated")
        )).all()

    drugs: dict[str, DrugRecord] = {}
    for drug_id, class_name, ingr_name in drug_rows:
        codes = frozenset(
            item["dur_code"]
            for item in (ingr_name or [])
            if isinstance(item, dict) and item.get("dur_code")
        )
        drugs[str(drug_id)] = DrugRecord(str(drug_id), class_name, codes)

    pairs = [(str(a), str(b)) for a, b in pair_rows]
    return drugs, pairs


def _build_node_index(drugs: dict[str, DrugRecord]) -> dict[str, int]:
    return {drug_id: idx for idx, drug_id in enumerate(drugs)}


def _split_edges(pairs: list[tuple[str, str]]) -> tuple[list, list]:
    shuffled = pairs[:]
    random.shuffle(shuffled)
    n_test = int(len(shuffled) * TEST_EDGE_FRACTION)
    return shuffled[n_test:], shuffled[:n_test]  # train, test


def _adjacency(train_pairs, node_index: dict[str, int], n_nodes: int) -> sparse.csr_matrix:
    rows, cols = [], []
    for a, b in train_pairs:
        i, j = node_index[a], node_index[b]
        rows += [i, j]
        cols += [j, i]
    data = np.ones(len(rows), dtype=np.float32)
    return sparse.csr_matrix((data, (rows, cols)), shape=(n_nodes, n_nodes))


def _class_pair_density(train_pairs, drugs: dict[str, DrugRecord]) -> dict[tuple[str, str], float]:
    """(class_i, class_j) 쌍의 train edge 수 / (class_i 크기 * class_j 크기) — 계열간 위험 밀도."""
    class_sizes: dict[str, int] = {}
    for d in drugs.values():
        c = d.class_name or "UNKNOWN"
        class_sizes[c] = class_sizes.get(c, 0) + 1

    edge_counts: dict[tuple[str, str], int] = {}
    for a, b in train_pairs:
        ca = drugs[a].class_name or "UNKNOWN"
        cb = drugs[b].class_name or "UNKNOWN"
        key = tuple(sorted((ca, cb)))
        edge_counts[key] = edge_counts.get(key, 0) + 1

    density = {}
    for key, count in edge_counts.items():
        ca, cb = key
        denom = class_sizes[ca] * class_sizes[cb]
        density[key] = count / denom if denom > 0 else 0.0
    return density


def _pair_features(
    a: str, b: str,
    drugs: dict[str, DrugRecord],
    node_index: dict[str, int],
    embeddings: np.ndarray,
    class_density: dict[tuple[str, str], float],
) -> list[float]:
    da, db = drugs[a], drugs[b]
    same_class = 1.0 if da.class_name and da.class_name == db.class_name else 0.0

    key = tuple(sorted((da.class_name or "UNKNOWN", db.class_name or "UNKNOWN")))
    density = class_density.get(key, 0.0)

    both_have_ingr = 1.0 if (da.dur_codes and db.dur_codes) else 0.0
    if da.dur_codes and db.dur_codes:
        inter = len(da.dur_codes & db.dur_codes)
        union = len(da.dur_codes | db.dur_codes)
        jaccard = inter / union if union else 0.0
    else:
        jaccard = 0.0

    ea, eb = embeddings[node_index[a]], embeddings[node_index[b]]
    dot = float(np.dot(ea, eb))
    na, nb = np.linalg.norm(ea), np.linalg.norm(eb)
    cosine = float(dot / (na * nb)) if na > 0 and nb > 0 else 0.0
    l2 = float(np.linalg.norm(ea - eb))

    return [same_class, density, jaccard, both_have_ingr, dot, cosine, l2]


FEATURE_NAMES = [
    "same_class", "class_pair_density", "ingr_jaccard", "both_have_ingr",
    "embedding_dot", "embedding_cosine", "embedding_l2dist",
]


def _sample_negatives(
    n: int, candidate_ids: list[str], positive_set: set[tuple[str, str]]
) -> list[tuple[str, str]]:
    """candidate_ids 안에서만 음성 쌍을 뽑는다.

    전체 35,299개 약품 중 77%는 DUR에 상호작용 기록이 아예 없는 '완전 고립' 노드다.
    이 전체 인구에서 균일하게 음성을 뽑으면, 양성 쌍(둘 다 그래프에 연결된 노드)과
    음성 쌍(대부분 한쪽 이상이 고립 노드 → 임베딩이 정확히 0벡터)이 임베딩 특징
    하나만으로 거의 완벽히 분리되어 '가짜로 쉬운' 과제가 된다 — 실제로 이 문제로
    AUROC=1.0이 나왔었다. candidate_ids를 '이미 알려진 상호작용이 하나 이상 있는
    약품' 집합으로 제한하면 훨씬 더 현실적인(어려운) 음성 쌍이 만들어진다.
    """
    negatives = []
    seen = set()
    attempts = 0
    max_attempts = n * 50
    while len(negatives) < n and attempts < max_attempts:
        attempts += 1
        a, b = random.choice(candidate_ids), random.choice(candidate_ids)
        if a == b:
            continue
        key = tuple(sorted((a, b)))
        if key in positive_set or key in seen:
            continue
        seen.add(key)
        negatives.append((a, b))
    return negatives


def _precision_at_k(y_true: np.ndarray, y_score: np.ndarray, k: int) -> float:
    order = np.argsort(-y_score)[:k]
    return float(np.mean(y_true[order]))


def _class_pair_key(a: str, b: str, drugs: dict[str, DrugRecord]) -> tuple[str, str]:
    return tuple(sorted((drugs[a].class_name or "UNKNOWN", drugs[b].class_name or "UNKNOWN")))


def _class_pair_holdout_experiment(
    drugs: dict[str, DrugRecord], pairs: list[tuple[str, str]],
    node_index: dict[str, int], node_ids: list[str], n_nodes: int,
) -> dict:
    """더 엄격한 일반화 테스트: 개별 엣지가 아니라 (계열,계열) 조합 자체를 통째로 hold-out한다.

    무작위 엣지 분할은 하나의 (class_i, class_j) 규칙이 수백~수천 개 제품쌍으로
    전개되어 있어서, 15%만 떼어내도 거의 모든 class-pair가 train에 남는다 —
    즉 '이미 본 규칙의 새 제품쌍'만 테스트하는 셈이라 낙관적이다. 여기서는
    class-pair 자체를 15% 통째로 분리해 '한 번도 본 적 없는 계열 조합'에
    대한 진짜 일반화 성능을 측정한다.
    """
    class_pairs = {}
    for a, b in pairs:
        class_pairs.setdefault(_class_pair_key(a, b, drugs), []).append((a, b))

    keys = list(class_pairs.keys())
    random.shuffle(keys)
    n_holdout = max(1, int(len(keys) * TEST_EDGE_FRACTION))
    holdout_keys = set(keys[:n_holdout])

    train_pairs2, test_pos_pairs2 = [], []
    for key, edges in class_pairs.items():
        (test_pos_pairs2 if key in holdout_keys else train_pairs2).extend(edges)

    if len(test_pos_pairs2) < 20:
        return {"skipped": "테스트 class-pair 엣지가 너무 적음"}

    adj2 = _adjacency(train_pairs2, node_index, n_nodes)
    svd2 = TruncatedSVD(n_components=EMBEDDING_DIM, random_state=RANDOM_SEED)
    embeddings2 = svd2.fit_transform(adj2).astype(np.float32)
    class_density2 = _class_pair_density(train_pairs2, drugs)  # 정의상 holdout class-pair는 0

    connected2 = sorted({a for a, b in train_pairs2} | {b for a, b in train_pairs2})
    full_positive_set = {tuple(sorted(p)) for p in pairs}

    train_neg2 = _sample_negatives(len(train_pairs2), connected2, full_positive_set)

    X_train, y_train = [], []
    for a, b in train_pairs2:
        X_train.append(_pair_features(a, b, drugs, node_index, embeddings2, class_density2))
        y_train.append(1)
    for a, b in train_neg2:
        X_train.append(_pair_features(a, b, drugs, node_index, embeddings2, class_density2))
        y_train.append(0)

    model2 = HistGradientBoostingClassifier(random_state=RANDOM_SEED, max_iter=300)
    model2.fit(np.array(X_train), np.array(y_train))

    # 음성도 반드시 holdout class-pair 내부에서 뽑아야 '새 계열 조합' 과제가 유지된다
    holdout_nodes = sorted({n for key in holdout_keys for a, b in class_pairs[key] for n in (a, b)})
    test_neg2 = _sample_negatives(len(test_pos_pairs2), holdout_nodes, full_positive_set)
    # class-pair가 holdout 밖인 음성은 걸러낸다 (진짜 신규 계열 조합만 평가에 남기기 위함)
    test_neg2 = [(a, b) for a, b in test_neg2 if _class_pair_key(a, b, drugs) in holdout_keys]

    X_test, y_test = [], []
    for a, b in test_pos_pairs2:
        X_test.append(_pair_features(a, b, drugs, node_index, embeddings2, class_density2))
        y_test.append(1)
    for a, b in test_neg2:
        X_test.append(_pair_features(a, b, drugs, node_index, embeddings2, class_density2))
        y_test.append(0)

    if len(set(y_test)) < 2 or len(test_neg2) < 5:
        return {"skipped": "holdout 내 음성 쌍을 충분히 만들지 못함"}

    X_test, y_test = np.array(X_test), np.array(y_test)
    score = model2.predict_proba(X_test)[:, 1]

    return {
        "n_holdout_class_pairs": len(holdout_keys),
        "n_test_positive_edges": len(test_pos_pairs2),
        "n_test_negative_edges": len(test_neg2),
        "auroc": round(float(roc_auc_score(y_test, score)), 4),
        "auprc": round(float(average_precision_score(y_test, score)), 4),
    }


async def main():
    t0 = time.time()
    print("[1/6] DB에서 drugs / drug_interactions 로딩")
    drugs, pairs = await _load_data()
    print(f"  drugs={len(drugs):,}  positive_pairs={len(pairs):,}")

    node_index = _build_node_index(drugs)
    node_ids = list(node_index.keys())
    n_nodes = len(node_ids)

    print("[2/6] train/test 엣지 분리 (누수 방지 — 임베딩·prior는 train만 사용)")
    train_pairs, test_pos_pairs = _split_edges(pairs)
    print(f"  train={len(train_pairs):,}  test_positive={len(test_pos_pairs):,}")

    print("[3/6] 그래프 임베딩 (TruncatedSVD on train adjacency)")
    adj = _adjacency(train_pairs, node_index, n_nodes)
    svd = TruncatedSVD(n_components=EMBEDDING_DIM, random_state=RANDOM_SEED)
    embeddings = svd.fit_transform(adj).astype(np.float32)
    print(f"  explained_variance_ratio(sum)={svd.explained_variance_ratio_.sum():.4f}")

    class_density = _class_pair_density(train_pairs, drugs)

    # '고립 노드'(DUR 상호작용이 하나도 없는 약품, 전체의 약 77%)를 후보에서 배제한다.
    # 이 노드들은 그래프 임베딩이 정확히 0벡터이므로, 여기서 무작위로 음성을 뽑으면
    # '임베딩이 0이냐 아니냐'만으로 거의 완벽히 분리되는 가짜로 쉬운 과제가 된다.
    connected_ids = sorted({a for a, b in pairs} | {b for a, b in pairs})
    print(f"  연결된 약품(하드 네거티브 후보): {len(connected_ids):,} / {n_nodes:,}")

    print("[4/6] 학습셋 구성 (train positive + 하드 네거티브)")
    full_positive_set = {tuple(sorted(p)) for p in pairs}  # 음성 샘플링 시 test까지 포함해 진짜 음성만 뽑음
    train_neg_pairs = _sample_negatives(len(train_pairs), connected_ids, full_positive_set)

    X_train, y_train = [], []
    for a, b in train_pairs:
        X_train.append(_pair_features(a, b, drugs, node_index, embeddings, class_density))
        y_train.append(1)
    for a, b in train_neg_pairs:
        X_train.append(_pair_features(a, b, drugs, node_index, embeddings, class_density))
        y_train.append(0)
    X_train, y_train = np.array(X_train), np.array(y_train)

    print("[5/6] HistGradientBoostingClassifier 학습")
    model = HistGradientBoostingClassifier(random_state=RANDOM_SEED, max_iter=300)
    model.fit(X_train, y_train)

    print("[6/6] 평가 (held-out test edges, 학습에 전혀 사용되지 않은 엣지)")

    def _evaluate(neg_pairs: list[tuple[str, str]]) -> dict:
        X, y = [], []
        for a, b in test_pos_pairs:
            X.append(_pair_features(a, b, drugs, node_index, embeddings, class_density))
            y.append(1)
        for a, b in neg_pairs:
            X.append(_pair_features(a, b, drugs, node_index, embeddings, class_density))
            y.append(0)
        X, y = np.array(X), np.array(y)
        score = model.predict_proba(X)[:, 1]
        return {
            "auroc": round(float(roc_auc_score(y, score)), 4),
            "auprc": round(float(average_precision_score(y, score)), 4),
            "precision_at_100": round(_precision_at_k(y, score, 100), 4),
            "precision_at_1000": round(_precision_at_k(y, score, min(1000, len(y))), 4),
            "n_negatives": len(neg_pairs),
        }

    n_test_neg = len(test_pos_pairs) * NEGATIVE_TO_POSITIVE_RATIO
    hard_test_neg = _sample_negatives(n_test_neg, connected_ids, full_positive_set)
    easy_test_neg = _sample_negatives(n_test_neg, node_ids, full_positive_set)

    eval_hard = _evaluate(hard_test_neg)   # 주 지표 — 둘 다 '이미 뭔가와 상호작용하는' 약품 사이에서 판별
    eval_easy = _evaluate(easy_test_neg)   # 참고 지표 — 전체 인구 무작위 (낙관적으로 부풀려짐, 참고용)

    # permutation importance — HistGradientBoostingClassifier는 feature_importances_가 없음
    X_hard, y_hard = [], []
    for a, b in test_pos_pairs:
        X_hard.append(_pair_features(a, b, drugs, node_index, embeddings, class_density))
        y_hard.append(1)
    for a, b in hard_test_neg:
        X_hard.append(_pair_features(a, b, drugs, node_index, embeddings, class_density))
        y_hard.append(0)
    from sklearn.inspection import permutation_importance
    perm = permutation_importance(
        model, np.array(X_hard), np.array(y_hard),
        n_repeats=5, random_state=RANDOM_SEED, scoring="roc_auc",
    )
    feature_importance = dict(zip(FEATURE_NAMES, perm.importances_mean.round(4).tolist()))

    print("[7/6] 엄격한 일반화 테스트 — 완전히 새로운 (계열,계열) 조합 hold-out")
    novel_class_pair_eval = _class_pair_holdout_experiment(drugs, pairs, node_index, node_ids, n_nodes)

    report = {
        "n_drugs": n_nodes,
        "n_connected_drugs": len(connected_ids),
        "n_positive_pairs": len(pairs),
        "n_train_edges": len(train_pairs),
        "n_test_edges": len(test_pos_pairs),
        "embedding_dim": EMBEDDING_DIM,
        "eval_hard_negatives__PRIMARY": eval_hard,
        "eval_easy_negatives__reference_only": eval_easy,
        "eval_novel_class_pairs__STRICT": novel_class_pair_eval,
        "feature_importance_permutation_auroc_drop": feature_importance,
        "elapsed_sec": round(time.time() - t0, 1),
        "caveat": (
            "DUR에 없는 쌍이 '안전'이라는 보장은 없음 — 음성 라벨은 무작위 샘플링 근사치. "
            "eval_hard_negatives(무작위 엣지 15% 분할)는 '이미 알려진 계열 조합의 새 제품쌍'만 "
            "테스트하므로 낙관적임 (같은 class-pair 규칙이 보통 train에도 남아있음). "
            "eval_novel_class_pairs(계열 조합 자체를 15% 통째로 hold-out)가 가장 정직한 지표 — "
            "모델이 한 번도 보지 못한 계열 조합에 대한 진짜 일반화 성능. "
            "eval_easy_negatives는 참고용이며 가장 낙관적으로 나옴."
        ),
    }

    print("\n===== 평가 결과 =====")
    print(json.dumps(report, ensure_ascii=False, indent=2))

    import os
    os.makedirs(ARTIFACT_DIR, exist_ok=True)
    joblib.dump({
        "model": model,
        "node_index": node_index,
        "embeddings": embeddings,
        "class_density": class_density,
        "feature_names": FEATURE_NAMES,
    }, f"{ARTIFACT_DIR}/ddi_model.joblib")
    with open(f"{ARTIFACT_DIR}/eval_report.json", "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n[저장] {ARTIFACT_DIR}/ddi_model.joblib, {ARTIFACT_DIR}/eval_report.json")


if __name__ == "__main__":
    asyncio.run(main())
