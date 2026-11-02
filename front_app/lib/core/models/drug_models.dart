class DrugSearchResult {
  final String id;
  final String itemName;
  final String? simpleName;
  final String? entpName;
  final String? className;
  final String? etcOtcName;
  final String? efcyQesitm;
  final String? useMethodQesitm;
  final String? atpnWarnQesitm;
  final String? atpnQesitm;
  final String? intrcQesitm;
  final String? seQesitm;
  final String? depositMethodQesitm;

  DrugSearchResult.fromJson(Map<String, dynamic> j)
      : id = j['id'],
        itemName = j['item_name'],
        simpleName = j['simple_name'],
        entpName = j['entp_name'],
        className = j['class_name'],
        etcOtcName = j['etc_otc_name'],
        efcyQesitm = j['efcy_qesitm'],
        useMethodQesitm = j['use_method_qesitm'],
        atpnWarnQesitm = j['atpn_warn_qesitm'],
        atpnQesitm = j['atpn_qesitm'],
        intrcQesitm = j['intrc_qesitm'],
        seQesitm = j['se_qesitm'],
        depositMethodQesitm = j['deposit_method_qesitm'];

  String get displayName =>
      (simpleName?.isNotEmpty == true) ? simpleName! : itemName;
}

/// 약봉투·처방전에서 읽은 복용 안내(서버 OCR). 못 읽은 항목은 null.
class OcrDose {
  final double? unitsPerIntake;
  final int? timesPerDay;
  final int? durationDays;

  OcrDose.fromJson(Map<String, dynamic> j)
      : unitsPerIntake = (j['units_per_intake'] as num?)?.toDouble(),
        timesPerDay = j['times_per_day'],
        durationDays = j['duration_days'];

  /// 복약함에 담을 때 함께 보낼 값 — 읽은 것만.
  Map<String, dynamic> toBoxFields() => {
        if (unitsPerIntake != null && timesPerDay != null) ...{
          'units_per_intake': unitsPerIntake,
          'times_per_day': timesPerDay,
        },
        if (durationDays != null) 'intake_duration_days': durationDays,
      };
}

class DrugNameMatchResult {
  final String queriedName;
  final DrugSearchResult? matched;
  final List<DrugSearchResult> alternatives;
  final OcrDose? dose;

  DrugNameMatchResult.fromJson(Map<String, dynamic> j)
      : queriedName = j['queried_name'],
        matched =
            j['matched'] != null ? DrugSearchResult.fromJson(j['matched']) : null,
        alternatives = (j['alternatives'] as List? ?? [])
            .map((e) => DrugSearchResult.fromJson(e))
            .toList(),
        dose = j['dose'] != null ? OcrDose.fromJson(j['dose']) : null;
}
