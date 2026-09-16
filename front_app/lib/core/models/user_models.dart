class UserProfile {
  final String id;
  final String email;
  final String name;
  final String? phoneNumber;
  final List<String> healthConditions;
  final List<String> allergyInfo;
  final int? birthYear;

  UserProfile.fromJson(Map<String, dynamic> j)
      : id = j['id'],
        email = j['email'],
        name = j['name'],
        phoneNumber = j['phone_number'],
        healthConditions = (j['health_conditions'] as List? ?? [])
            .map((e) => e.toString())
            .toList(),
        allergyInfo = (j['allergy_info'] as List? ?? [])
            .map((e) => e.toString())
            .toList(),
        birthYear = j['birth_year'];
}
