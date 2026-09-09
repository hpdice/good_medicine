class MedicineBoxDrug {
  final String id;
  final String itemName;
  final String? simpleName;
  final String? entpName;
  final String? className;
  final String? etcOtcName;
  final String? efcyQesitm;
  final String? itemImage;

  MedicineBoxDrug.fromJson(Map<String, dynamic> j)
      : id = j['id'],
        itemName = j['item_name'],
        simpleName = j['simple_name'],
        entpName = j['entp_name'],
        className = j['class_name'],
        etcOtcName = j['etc_otc_name'],
        efcyQesitm = j['efcy_qesitm'],
        itemImage = j['item_image'];

  String get displayName =>
      (simpleName?.isNotEmpty == true) ? simpleName! : itemName;
}

class MedicineBoxEntry {
  final String id;
  final MedicineBoxDrug drug;
  final bool isCurrent;
  final String addedMethod;
  final String createdAt;

  MedicineBoxEntry.fromJson(Map<String, dynamic> j)
      : id = j['id'],
        drug = MedicineBoxDrug.fromJson(j['drug']),
        isCurrent = j['is_current'],
        addedMethod = j['added_method'],
        createdAt = j['created_at'];
}
