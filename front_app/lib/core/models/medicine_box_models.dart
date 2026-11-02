class MedicineBoxDrug {
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

  MedicineBoxDrug.fromJson(Map<String, dynamic> j)
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

/// 복용량 숫자 표시 — 1.0은 "1", 0.5는 "0.5".
String formatCount(double v) =>
    v == v.roundToDouble() ? v.toInt().toString() : v.toString();

class MedicineBoxEntry {
  final String id;
  final MedicineBoxDrug drug;
  final int? intakeDurationDays;
  // 용량 확인(DUR 하루 최대량)에 쓰는 복용량 — 1회 정·캡슐 개수, 하루 복용 횟수
  final double? unitsPerIntake;
  final int? timesPerDay;
  final List<String> intakeTimes; // HH:MM, 매일 이 시각에 복약 알림
  final bool reminderEnabled;
  final bool isCurrent;
  final String addedMethod;
  final String createdAt;

  MedicineBoxEntry.fromJson(Map<String, dynamic> j)
      : id = j['id'],
        drug = MedicineBoxDrug.fromJson(j['drug']),
        intakeDurationDays = j['intake_duration_days'],
        unitsPerIntake = (j['units_per_intake'] as num?)?.toDouble(),
        timesPerDay = j['times_per_day'],
        intakeTimes = (j['intake_times'] as List? ?? [])
            .map((e) => e.toString())
            .toList(),
        reminderEnabled = j['reminder_enabled'] ?? false,
        isCurrent = j['is_current'],
        addedMethod = j['added_method'],
        createdAt = j['created_at'];

  /// "1회 1개 · 하루 2번" — 둘 다 있을 때만.
  String? get doseLabel => unitsPerIntake != null && timesPerDay != null
      ? '1회 ${formatCount(unitsPerIntake!)}개 · 하루 $timesPerDay번'
      : null;
}
