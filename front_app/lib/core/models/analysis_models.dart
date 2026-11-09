class FindingItem {
  final String drug1Id, drug1Name, drug2Id, drug2Name, interactionType;
  final String? mechanism;
  final List<String> riskTags; // mechanism 문장에서 뽑은 위험/증상 태그
  final String source; // ingredient(성분 단위 판정) / residual(성분코드 미해소 약 폴백)
  // "자세히 보기" 토글용 — 병용금기의 실제 성분쌍(drug1↔ingrA, drug2↔ingrB).
  // 성분 경로 병용금기일 때만 값이 있음.
  final String? ingrA, ingrB;

  bool get hasIngredientDetail => ingrA != null && ingrB != null;

  FindingItem.fromJson(Map<String, dynamic> j)
      : drug1Id = j['drug1_id'],
        drug1Name = j['drug1_name'],
        drug2Id = j['drug2_id'],
        drug2Name = j['drug2_name'],
        interactionType = j['interaction_type'],
        mechanism = j['mechanism'],
        riskTags = (j['risk_tags'] as List? ?? []).map((e) => e.toString()).toList(),
        source = j['source'] ?? 'ingredient',
        ingrA = j['ingr_a'],
        ingrB = j['ingr_b'];
}

/// 사용자의 건강 상태가 약 허가사항 "다음 환자에는 투여하지 말 것" 항목에 있는 경우 — `sentence`는 그 항목 원문.
class ConditionTabooItem {
  final String drugId, drugName, condition, sentence;

  ConditionTabooItem.fromJson(Map<String, dynamic> j)
      : drugId = j['drug_id'],
        drugName = j['drug_name'],
        condition = j['condition'],
        sentence = j['sentence'];
}

class AgeCautionItem {
  final String drugId, drugName, ruleType; // age_taboo(금기) / elderly_caution(주의)
  final String? prohibitContent;

  AgeCautionItem.fromJson(Map<String, dynamic> j)
      : drugId = j['drug_id'],
        drugName = j['drug_name'],
        ruleType = j['rule_type'],
        prohibitContent = j['prohibit_content'];
}

class PregnancyCautionItem {
  final String drugId, drugName;
  final String? prohibitContent; // 등급·근거가 섞인 DUR 원문
  final String? remark; // 적용 범위 (예: '경구')

  PregnancyCautionItem.fromJson(Map<String, dynamic> j)
      : drugId = j['drug_id'],
        drugName = j['drug_name'],
        prohibitContent = j['prohibit_content'],
        remark = j['remark'];
}

/// DUR 용량주의 — 하루에 먹는 성분 양이 하루 최대 투여량을 넘음. scope: total(여러 약 합계) / product(복합제 한 품목).
class DoseCautionItem {
  final List<String> drugIds, drugNames, uncountedDrugNames;
  final String ingredient, scope;
  final double dailyMg, maxDailyMg;
  final String? prohibitContent;

  DoseCautionItem.fromJson(Map<String, dynamic> j)
      : drugIds = (j['drug_ids'] as List? ?? []).map((e) => e.toString()).toList(),
        drugNames = (j['drug_names'] as List? ?? []).map((e) => e.toString()).toList(),
        uncountedDrugNames = (j['uncounted_drug_names'] as List? ?? [])
            .map((e) => e.toString())
            .toList(),
        ingredient = j['ingredient'],
        scope = j['scope'] ?? 'total',
        dailyMg = (j['daily_mg'] as num).toDouble(),
        maxDailyMg = (j['max_daily_mg'] as num).toDouble(),
        prohibitContent = j['prohibit_content'];
}

/// 성분코드가 없어 성분 규칙(병용금기·중복·연령·하루 용량)을 적용하지 못한 약 — "위험 없음"이 아니라 "확인하지 못함".
class UnresolvedDrugItem {
  final String drugId, drugName;

  UnresolvedDrugItem.fromJson(Map<String, dynamic> j)
      : drugId = j['drug_id'],
        drugName = j['drug_name'];
}

class QuickCheckResponse {
  final int totalDrugs;
  final bool hasContraindication;
  final String riskLevel; // safe / caution / critical
  final int contraindicatedCount;
  final int duplicateEffectGroupCount;
  final int duplicateIngredientCount;
  final int ageTabooCount;
  final int elderlyCautionCount;
  final int pregnancyTabooCount;
  final int doseCautionCount;
  final int conditionTabooCount;
  final List<FindingItem> findings;
  final List<ConditionTabooItem> conditionTaboos;
  final List<AgeCautionItem> ageCautions;
  final List<PregnancyCautionItem> pregnancyCautions;
  final List<DoseCautionItem> doseCautions;
  final List<UnresolvedDrugItem> unresolvedDrugs;

  QuickCheckResponse.fromJson(Map<String, dynamic> j)
      : totalDrugs = j['total_drugs'],
        hasContraindication = j['has_contraindication'],
        riskLevel = j['risk_level'],
        contraindicatedCount = j['contraindicated_count'],
        duplicateEffectGroupCount = j['duplicate_effect_group_count'] ?? 0,
        duplicateIngredientCount = j['duplicate_ingredient_count'] ?? 0,
        ageTabooCount = j['age_taboo_count'] ?? 0,
        elderlyCautionCount = j['elderly_caution_count'] ?? 0,
        pregnancyTabooCount = j['pregnancy_taboo_count'] ?? 0,
        doseCautionCount = j['dose_caution_count'] ?? 0,
        conditionTabooCount = j['condition_taboo_count'] ?? 0,
        findings = (j['findings'] as List? ?? [])
            .map((e) => FindingItem.fromJson(e))
            .toList(),
        conditionTaboos = (j['condition_taboos'] as List? ?? [])
            .map((e) => ConditionTabooItem.fromJson(e))
            .toList(),
        ageCautions = (j['age_cautions'] as List? ?? [])
            .map((e) => AgeCautionItem.fromJson(e))
            .toList(),
        pregnancyCautions = (j['pregnancy_cautions'] as List? ?? [])
            .map((e) => PregnancyCautionItem.fromJson(e))
            .toList(),
        doseCautions = (j['dose_cautions'] as List? ?? [])
            .map((e) => DoseCautionItem.fromJson(e))
            .toList(),
        unresolvedDrugs = (j['unresolved_drugs'] as List? ?? [])
            .map((e) => UnresolvedDrugItem.fromJson(e))
            .toList();
}

/// AI 설명이 근거로 쓴 용어 풀이의 출처(기관 문서 이름).
class GuideSourceItem {
  final String name, url;

  GuideSourceItem.fromJson(Map<String, dynamic> j)
      : name = j['name'],
        url = j['url'] ?? '';
}

class AnalysisGuideResponse {
  final String riskLevel;
  final String guideText;
  final bool isAiGenerated;
  final String disclaimer;
  final String? modelName; // AI가 쓴 설명일 때만 값이 있다
  final List<GuideSourceItem> glossarySources;

  AnalysisGuideResponse.fromJson(Map<String, dynamic> j)
      : riskLevel = j['risk_level'],
        guideText = j['guide_text'],
        isAiGenerated = j['is_ai_generated'] ?? true,
        disclaimer = j['disclaimer'] ?? '',
        modelName = j['model_name'],
        glossarySources = (j['glossary_sources'] as List? ?? [])
            .map((e) => GuideSourceItem.fromJson(e))
            .toList();
}
