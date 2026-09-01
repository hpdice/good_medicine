class FindingItem {
  final String drug1Id, drug1Name, drug2Id, drug2Name, interactionType;
  final String? mechanism;
  final List<String> riskTags; // mechanism 문장에서 뽑은 위험/증상 태그
  final String source; // ingredient(성분 단위 판정) / residual(성분코드 미해소 약 폴백)

  FindingItem.fromJson(Map<String, dynamic> j)
      : drug1Id = j['drug1_id'],
        drug1Name = j['drug1_name'],
        drug2Id = j['drug2_id'],
        drug2Name = j['drug2_name'],
        interactionType = j['interaction_type'],
        mechanism = j['mechanism'],
        riskTags = (j['risk_tags'] as List? ?? []).map((e) => e.toString()).toList(),
        source = j['source'] ?? 'ingredient';
}

class QuickCheckResponse {
  final int totalDrugs;
  final bool hasContraindication;
  final String riskLevel; // safe / caution / critical
  final int contraindicatedCount;
  final int duplicateEffectGroupCount;
  final List<FindingItem> findings;

  QuickCheckResponse.fromJson(Map<String, dynamic> j)
      : totalDrugs = j['total_drugs'],
        hasContraindication = j['has_contraindication'],
        riskLevel = j['risk_level'],
        contraindicatedCount = j['contraindicated_count'],
        duplicateEffectGroupCount = j['duplicate_effect_group_count'] ?? 0,
        findings = (j['findings'] as List? ?? [])
            .map((e) => FindingItem.fromJson(e))
            .toList();
}

class AnalysisGuideResponse {
  final String riskLevel;
  final String guideText;
  final bool isAiGenerated;
  final String disclaimer;

  AnalysisGuideResponse.fromJson(Map<String, dynamic> j)
      : riskLevel = j['risk_level'],
        guideText = j['guide_text'],
        isAiGenerated = j['is_ai_generated'] ?? true,
        disclaimer = j['disclaimer'] ?? '';
}
