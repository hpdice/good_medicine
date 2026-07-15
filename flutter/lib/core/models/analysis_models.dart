class FindingItem {
  final String drug1Id, drug1Name, drug2Id, drug2Name, interactionType;
  final String? mechanism;

  FindingItem.fromJson(Map<String, dynamic> j)
      : drug1Id = j['drug1_id'],
        drug1Name = j['drug1_name'],
        drug2Id = j['drug2_id'],
        drug2Name = j['drug2_name'],
        interactionType = j['interaction_type'],
        mechanism = j['mechanism'];
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
