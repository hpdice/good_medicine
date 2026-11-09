class UserProfile {
  final String id;
  final String email;
  final String name;
  final List<String> healthConditions;
  final int? birthYear;
  final bool? isPregnant; // null = 미입력

  UserProfile.fromJson(Map<String, dynamic> j)
      : id = j['id'],
        email = j['email'],
        name = j['name'],
        healthConditions = (j['health_conditions'] as List? ?? [])
            .map((e) => e.toString())
            .toList(),
        birthYear = j['birth_year'],
        isPregnant = j['is_pregnant'];
}
