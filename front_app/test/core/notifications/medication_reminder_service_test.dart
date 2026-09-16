import 'package:flutter_test/flutter_test.dart';
import 'package:drugtest/core/models/medicine_box_models.dart';
import 'package:drugtest/core/notifications/medication_reminder_service.dart';

MedicineBoxEntry _entry({
  required String id,
  required String drugName,
  List<String> intakeTimes = const [],
  bool reminderEnabled = true,
  int? intakeDurationDays,
  String createdAt = '2026-01-01T00:00:00Z',
}) {
  return MedicineBoxEntry.fromJson({
    'id': id,
    'drug': {
      'id': 'drug-$id',
      'item_name': drugName,
      'simple_name': drugName,
      'entp_name': null,
      'class_name': null,
      'etc_otc_name': null,
      'efcy_qesitm': null,
      'item_image': null,
    },
    'dosage_per_intake': null,
    'intake_frequency': null,
    'intake_duration_days': intakeDurationDays,
    'intake_times': intakeTimes,
    'reminder_enabled': reminderEnabled,
    'is_current': true,
    'added_method': 'manual',
    'created_at': createdAt,
  });
}

void main() {
  group('computeSchedule', () {
    test('알림이 꺼져 있으면 스케줄에서 제외', () {
      final entry = _entry(
        id: 'a',
        drugName: '테스트약',
        intakeTimes: const ['08:00'],
        reminderEnabled: false,
      );
      expect(MedicationReminderService.computeSchedule([entry]), isEmpty);
    });

    test('intake_times가 비어 있으면 제외', () {
      final entry = _entry(id: 'a', drugName: '테스트약', intakeTimes: const []);
      expect(MedicationReminderService.computeSchedule([entry]), isEmpty);
    });

    test('시각 여러 개 → 각각 별도 리마인더로 매일 반복', () {
      final entry = _entry(
        id: 'a',
        drugName: '테스트약',
        intakeTimes: const ['08:00', '20:30'],
      );
      final schedule = MedicationReminderService.computeSchedule([entry]);
      expect(schedule.length, 2);
      expect(schedule.map((r) => (r.hour, r.minute)),
          containsAll([(8, 0), (20, 30)]));
    });

    test('intake_duration_days 만료 전이면 포함', () {
      final now = DateTime(2026, 1, 5);
      final entry = _entry(
        id: 'a',
        drugName: '테스트약',
        intakeTimes: const ['08:00'],
        intakeDurationDays: 10,
        createdAt: '2026-01-01T00:00:00Z',
      );
      final schedule =
          MedicationReminderService.computeSchedule([entry], now: now);
      expect(schedule, hasLength(1));
    });

    test('intake_duration_days 만료 후면 제외', () {
      final now = DateTime(2026, 2, 1);
      final entry = _entry(
        id: 'a',
        drugName: '테스트약',
        intakeTimes: const ['08:00'],
        intakeDurationDays: 10,
        createdAt: '2026-01-01T00:00:00Z',
      );
      final schedule =
          MedicationReminderService.computeSchedule([entry], now: now);
      expect(schedule, isEmpty);
    });

    test('intake_duration_days 없으면 기간 제한 없이 계속 포함', () {
      final now = DateTime(2030, 1, 1);
      final entry = _entry(
        id: 'a',
        drugName: '테스트약',
        intakeTimes: const ['08:00'],
        createdAt: '2026-01-01T00:00:00Z',
      );
      final schedule =
          MedicationReminderService.computeSchedule([entry], now: now);
      expect(schedule, hasLength(1));
    });
  });

  group('stableReminderId', () {
    test('같은 entry id·시각 인덱스는 항상 같은 id를 낸다', () {
      final id1 = MedicationReminderService.stableReminderId('entry-abc', 0);
      final id2 = MedicationReminderService.stableReminderId('entry-abc', 0);
      expect(id1, id2);
    });

    test('시각 인덱스가 다르면 id도 달라진다', () {
      final id0 = MedicationReminderService.stableReminderId('entry-abc', 0);
      final id1 = MedicationReminderService.stableReminderId('entry-abc', 1);
      expect(id0, isNot(id1));
    });

    test('id는 항상 음이 아닌 32bit 범위 안', () {
      final id = MedicationReminderService.stableReminderId(
          'some-random-uuid-entry-id', 3);
      expect(id, greaterThanOrEqualTo(0));
      expect(id, lessThan(1 << 31));
    });
  });
}
