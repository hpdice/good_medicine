import 'dart:async' show unawaited;

import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import 'package:timezone/data/latest.dart' as tzdata;
import 'package:timezone/timezone.dart' as tz;
import '../models/medicine_box_models.dart';

const _channel = AndroidNotificationChannel(
  'medication_reminders',
  '복약 알림',
  description: '등록한 시각에 약 복용을 알려줍니다',
  importance: Importance.high,
);

// zonedSchedule로 우리가 예약한 알림만 이 id 대역을 쓴다(entry.id.hashCode 기반) —
// FCM(fcm_service.dart)이 즉시 표시하는 알림의 notification.hashCode와 겹치지 않게
// 좁은 대역으로 제한해서, 재스케줄 시 cancelAll() 대신 이 대역만 골라 취소한다
// (cancelAll은 트레이에 떠 있는 병용금기 알림까지 지워버리는 부작용이 있어 피한다).
const _idRangeMax = 1000000;

class ScheduledReminder {
  final int id;
  final String entryId;
  final String drugName;
  final int hour;
  final int minute;

  const ScheduledReminder({
    required this.id,
    required this.entryId,
    required this.drugName,
    required this.hour,
    required this.minute,
  });
}

/// 복약함의 `intake_times`/`reminder_enabled`를 온디바이스 로컬 알림(Android)으로
/// 매일 반복 예약한다. 서버 사이드 스케줄러는 두지 않는다 — 앱이 복약함을 새로
/// 불러올 때마다(홈 진입·항목 추가/수정/삭제) 전체 재계산해서 다시 건다.
class MedicationReminderService {
  static bool _initialized = false;
  static bool _askedThisRun = false;
  static final _plugin = FlutterLocalNotificationsPlugin();

  static AndroidFlutterLocalNotificationsPlugin? _android() => _plugin
      .resolvePlatformSpecificImplementation<
        AndroidFlutterLocalNotificationsPlugin
      >();

  /// 이 앱의 알림이 지금 허용돼 있는지. 웹·안드로이드가 아닌 곳은 null.
  static Future<bool?> notificationsEnabled() async {
    if (kIsWeb) return null;
    await init();
    return _android()?.areNotificationsEnabled();
  }

  /// Android 13+는 알림 권한(POST_NOTIFICATIONS)을 사용자가 허용해야 알림이 뜬다. 설치 직후는 꺼져 있고,
  /// 앱이 요청하지 않으면 허용 창이 한 번도 안 떠서 상단 표시줄에도 알림이 안 온다. 이미 허용돼 있으면 창을 띄우지
  /// 않고 true를 돌려준다. 파이어베이스(FCM) 초기화와 무관하게 로컬 알림 쪽에서 직접 요청한다.
  static Future<bool> requestNotificationPermission() async {
    if (kIsWeb) return false;
    await init();
    final android = _android();
    if (android == null) return false;
    if (await android.areNotificationsEnabled() ?? false) return true;
    return await android.requestNotificationsPermission() ?? false;
  }

  /// 로그인해 홈에 들어오면 앱 실행당 한 번 알림 허용 창을 띄운다. 복약 알림을 아직 하나도 안 켠 새 사용자도 대상이다
  /// (예약된 알림이 있을 때만 물으면 설치 직후엔 영영 안 묻는다). 목록 불러오기를 막지 않게 기다리지 않는다.
  static void askPermissionOncePerRun() {
    if (kIsWeb || _askedThisRun) return;
    _askedThisRun = true;
    unawaited(requestNotificationPermission());
  }

  static Future<void> init() async {
    if (_initialized) return;
    tzdata.initializeTimeZones();
    try {
      tz.setLocalLocation(tz.getLocation('Asia/Seoul'));
    } catch (_) {
      // 타임존 DB에 없으면 기기 로컬 설정 그대로 둔다 — 치명적이지 않음.
    }
    const androidInit = AndroidInitializationSettings('@mipmap/ic_launcher');
    await _plugin.initialize(
      const InitializationSettings(android: androidInit),
    );
    await _plugin
        .resolvePlatformSpecificImplementation<
          AndroidFlutterLocalNotificationsPlugin
        >()
        ?.createNotificationChannel(_channel);
    _initialized = true;
  }

  /// 순수 계산부(테스트 대상) — `intake_duration_days`가 있고 오늘 기준 이미
  /// 만료됐으면 제외한다. `createdAt`을 복용 시작일 근사치로 쓴다(정확한
  /// 처방일이 없을 수 있어서).
  static List<ScheduledReminder> computeSchedule(
    List<MedicineBoxEntry> entries, {
    DateTime? now,
  }) {
    final today = now ?? DateTime.now();
    final result = <ScheduledReminder>[];
    for (final entry in entries) {
      if (!entry.reminderEnabled || entry.intakeTimes.isEmpty) continue;
      if (_isExpired(entry, today)) continue;
      for (var i = 0; i < entry.intakeTimes.length; i++) {
        final parts = entry.intakeTimes[i].split(':');
        if (parts.length != 2) continue;
        final hour = int.tryParse(parts[0]);
        final minute = int.tryParse(parts[1]);
        if (hour == null || minute == null) continue;
        result.add(
          ScheduledReminder(
            id: stableReminderId(entry.id, i),
            entryId: entry.id,
            drugName: entry.drug.displayName,
            hour: hour,
            minute: minute,
          ),
        );
      }
    }
    return result;
  }

  static bool _isExpired(MedicineBoxEntry entry, DateTime today) {
    final duration = entry.intakeDurationDays;
    if (duration == null) return false;
    final started = DateTime.tryParse(entry.createdAt);
    if (started == null) return false;
    return today.isAfter(started.add(Duration(days: duration)));
  }

  /// entry id(UUID 문자열)+시각 인덱스 → 안정적인 32bit 정수 알림 id.
  /// 같은 entry·시각이면 재계산해도 항상 같은 id가 나와 재스케줄이 깨끗하게 맞물린다.
  static int stableReminderId(String entryId, int timeIndex) =>
      (entryId.hashCode & 0x7fffffff) % (_idRangeMax ~/ 10) * 10 + timeIndex;

  /// 현재 목록 기준으로 알림을 전부 재계산해 다시 건다. 우리 id 대역만 취소하고
  /// (cancelAll 아님) 새로 스케줄한다.
  static Future<void> reschedule(List<MedicineBoxEntry> entries) async {
    // 웹에는 로컬 알림 플러그인이 없어 호출하면 예외가 난다. 이 예외가 삭제·복용량 수정의 화면 갱신
    // (notifyListeners)을 건너뛰게 만들어 판정 배너가 옛 상태로 남았다.
    if (kIsWeb) return;
    if (!_initialized) await init();

    final reminders = computeSchedule(entries);

    final pending = await _plugin.pendingNotificationRequests();
    for (final p in pending) {
      if (p.id >= 0 && p.id < _idRangeMax) {
        await _plugin.cancel(p.id);
      }
    }

    for (final reminder in reminders) {
      await _plugin.zonedSchedule(
        reminder.id,
        '복약 알림',
        '${reminder.drugName} 복용할 시간이에요',
        _nextInstance(reminder.hour, reminder.minute),
        NotificationDetails(
          android: AndroidNotificationDetails(
            _channel.id,
            _channel.name,
            channelDescription: _channel.description,
            importance: Importance.high,
            priority: Priority.high,
          ),
        ),
        androidScheduleMode: AndroidScheduleMode.inexactAllowWhileIdle,
        matchDateTimeComponents: DateTimeComponents.time,
        uiLocalNotificationDateInterpretation:
            UILocalNotificationDateInterpretation.absoluteTime,
      );
    }
  }

  static tz.TZDateTime _nextInstance(int hour, int minute) {
    final now = tz.TZDateTime.now(tz.local);
    var scheduled = tz.TZDateTime(
      tz.local,
      now.year,
      now.month,
      now.day,
      hour,
      minute,
    );
    if (scheduled.isBefore(now)) {
      scheduled = scheduled.add(const Duration(days: 1));
    }
    return scheduled;
  }
}
