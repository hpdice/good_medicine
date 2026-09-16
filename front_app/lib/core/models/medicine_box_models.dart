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

class MedicineBoxEntry {
  final String id;
  final MedicineBoxDrug drug;
  final int? intakeDurationDays;
  final List<String> intakeTimes; // HH:MM, 매일 이 시각에 복약 알림
  final bool reminderEnabled;
  final bool isCurrent;
  final String addedMethod;
  final String createdAt;

  MedicineBoxEntry.fromJson(Map<String, dynamic> j)
      : id = j['id'],
        drug = MedicineBoxDrug.fromJson(j['drug']),
        intakeDurationDays = j['intake_duration_days'],
        intakeTimes = (j['intake_times'] as List? ?? [])
            .map((e) => e.toString())
            .toList(),
        reminderEnabled = j['reminder_enabled'] ?? false,
        isCurrent = j['is_current'],
        addedMethod = j['added_method'],
        createdAt = j['created_at'];
}
