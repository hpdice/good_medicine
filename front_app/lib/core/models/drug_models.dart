class DrugSearchResult {
  final String id;
  final String itemName;
  final String? simpleName;
  final String? entpName;
  final String? className;
  final String? etcOtcName;
  final String? efcyQesitm;

  DrugSearchResult.fromJson(Map<String, dynamic> j)
      : id = j['id'],
        itemName = j['item_name'],
        simpleName = j['simple_name'],
        entpName = j['entp_name'],
        className = j['class_name'],
        etcOtcName = j['etc_otc_name'],
        efcyQesitm = j['efcy_qesitm'];

  String get displayName =>
      (simpleName?.isNotEmpty == true) ? simpleName! : itemName;
}

class DrugNameMatchResult {
  final String queriedName;
  final DrugSearchResult? matched;
  final List<DrugSearchResult> alternatives;

  DrugNameMatchResult.fromJson(Map<String, dynamic> j)
      : queriedName = j['queried_name'],
        matched =
            j['matched'] != null ? DrugSearchResult.fromJson(j['matched']) : null,
        alternatives = (j['alternatives'] as List? ?? [])
            .map((e) => DrugSearchResult.fromJson(e))
            .toList();
}
