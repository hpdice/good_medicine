import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../../../core/models/medicine_box_models.dart';
import '../../../core/notifications/medication_reminder_service.dart';
import '../../../core/theme/app_theme.dart';
import '../home_provider.dart';

Future<void> showReminderEditSheet(
  BuildContext context,
  MedicineBoxEntry entry,
) {
  return showModalBottomSheet(
    context: context,
    isScrollControlled: true,
    builder: (_) => _ReminderEditSheet(entry: entry),
  );
}

class _ReminderEditSheet extends StatefulWidget {
  final MedicineBoxEntry entry;
  const _ReminderEditSheet({required this.entry});

  @override
  State<_ReminderEditSheet> createState() => _ReminderEditSheetState();
}

class _ReminderEditSheetState extends State<_ReminderEditSheet>
    with WidgetsBindingObserver {
  late List<String> _times;
  late bool _enabled;
  // 복용량 — 둘 다 있어야 하루 용량 확인에 쓰인다. null = 모름(입력 안 함)
  double? _units;
  int? _perDay;
  bool _saving = false;
  // 이 앱의 알림 허용 여부. null = 아직 모름·웹처럼 해당 없음
  bool? _notificationsAllowed;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _refreshPermission();
    _times = [...widget.entry.intakeTimes]..sort();
    _enabled = widget.entry.reminderEnabled;
    _units = widget.entry.unitsPerIntake;
    _perDay = widget.entry.timesPerDay;
  }

  Future<void> _refreshPermission() async {
    final allowed = await MedicationReminderService.notificationsEnabled();
    if (mounted) setState(() => _notificationsAllowed = allowed);
  }

  /// 시스템 알림 허용 창을 띄운다. 이미 거부해서 시스템이 창을 더는 안 띄우는 상태면, 앱 안에서 이유를 설명하고 허락을 받은 뒤
  /// 이 앱의 휴대폰 알림 설정 화면을 연다(말없이 설정 화면으로 보내지 않는다).
  Future<void> _askPermission() async {
    final allowed =
        await MedicationReminderService.requestNotificationPermission();
    if (!mounted) return;
    setState(() => _notificationsAllowed = allowed);
    if (allowed) return;
    final goSettings = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('알림 권한이 필요해요'),
        content: const Text(
          '복용 시간에 알려 드리려면 이 앱의 알림을 허용해야 해요. '
          '이전에 허용하지 않아 휴대폰이 허용 창을 다시 띄울 수 없는 상태예요.\n\n'
          '설정 화면에서 "알림"을 켜 주세요.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('나중에'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('설정으로 이동'),
          ),
        ],
      ),
    );
    if (goSettings == true) {
      await MedicationReminderService.openNotificationSettings();
    }
  }

  /// 설정 화면에서 앱으로 돌아오면 허용 여부를 다시 확인한다.
  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) _refreshPermission();
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  Future<void> _pickTime() async {
    final picked = await showTimePicker(
      context: context,
      initialTime: TimeOfDay.now(),
    );
    if (picked == null) return;
    final formatted =
        '${picked.hour.toString().padLeft(2, '0')}:${picked.minute.toString().padLeft(2, '0')}';
    if (_times.contains(formatted)) return;
    setState(() => _times = [..._times, formatted]..sort());
  }

  void _removeTime(String t) {
    setState(() => _times = _times.where((e) => e != t).toList());
  }

  Future<void> _save() async {
    setState(() => _saving = true);
    final home = context.read<HomeProvider>();
    final hasDose = _units != null && _perDay != null;
    final ok = await home.updateEntry(widget.entry.id, {
      'intake_times': _times,
      'reminder_enabled': _enabled,
      // 한쪽만 적으면 계산할 수 없으니 둘 다 있을 때만 저장하고, 아니면 지운다(null)
      'units_per_intake': hasDose ? _units : null,
      'times_per_day': hasDose ? _perDay : null,
    });
    if (!mounted) return;
    if (ok) {
      Navigator.of(context).pop();
    } else {
      setState(() => _saving = false);
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(const SnackBar(content: Text('저장에 실패했습니다.')));
    }
  }

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Padding(
      padding: EdgeInsets.only(
        left: 20,
        right: 20,
        top: 16,
        bottom: MediaQuery.of(context).viewInsets.bottom + 20,
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            '복용량 · 알림',
            style: Theme.of(
              context,
            ).textTheme.titleLarge?.copyWith(fontWeight: FontWeight.w700),
          ),
          Gap.v4,
          Text(
            widget.entry.drug.displayName,
            style: TextStyle(color: scheme.onSurfaceVariant),
          ),
          Gap.v16,
          Text('복용량', style: Theme.of(context).textTheme.titleSmall),
          Text(
            '적어 두면 하루에 먹는 양이 식약처 기준을 넘는지 확인해 드려요',
            style: TextStyle(fontSize: 12, color: scheme.onSurfaceVariant),
          ),
          Gap.v8,
          _Stepper(
            label: '1회',
            value: _units == null ? null : '${formatCount(_units!)}개',
            onMinus: _units == null || _units! <= 0.5
                ? null
                : () => setState(() => _units = _units! - 0.5),
            onPlus: () => setState(
              () => _units = _units == null
                  ? 1
                  : (_units! >= 20 ? 20 : _units! + 0.5),
            ),
          ),
          _Stepper(
            label: '하루',
            value: _perDay == null ? null : '$_perDay번',
            onMinus: _perDay == null || _perDay! <= 1
                ? null
                : () => setState(() => _perDay = _perDay! - 1),
            onPlus: () => setState(
              () => _perDay = _perDay == null
                  ? 1
                  : (_perDay! >= 12 ? 12 : _perDay! + 1),
            ),
          ),
          if (_units != null || _perDay != null)
            Align(
              alignment: Alignment.centerLeft,
              child: TextButton(
                onPressed: () => setState(() {
                  _units = null;
                  _perDay = null;
                }),
                child: const Text('복용량 지우기'),
              ),
            ),
          const Divider(height: 24),
          SwitchListTile(
            contentPadding: EdgeInsets.zero,
            title: const Text('알림 켜기'),
            subtitle: const Text('매일 아래 시각에 이 약 복용을 알려줍니다'),
            value: _enabled,
            onChanged: (v) {
              setState(() => _enabled = v);
              if (v) _askPermission();
            },
          ),
          if (_enabled && _notificationsAllowed == false)
            Container(
              margin: const EdgeInsets.only(top: 4, bottom: 4),
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: scheme.errorContainer,
                borderRadius: BorderRadius.circular(10),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    '이 앱의 알림이 꺼져 있어 알림이 오지 않아요.',
                    style: TextStyle(
                      fontWeight: FontWeight.w700,
                      color: scheme.onErrorContainer,
                    ),
                  ),
                  const SizedBox(height: 4),
                  Text(
                    '아래 버튼으로 허용하거나, 휴대폰 설정 > 앱 > 굿메디슨 > 알림에서 켜 주세요.',
                    style: TextStyle(
                      fontSize: 12.5,
                      color: scheme.onErrorContainer,
                    ),
                  ),
                  const SizedBox(height: 8),
                  FilledButton.tonal(
                    onPressed: _askPermission,
                    child: const Text('알림 허용하기'),
                  ),
                ],
              ),
            ),
          Gap.v8,
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              for (final t in _times)
                Chip(label: Text(t), onDeleted: () => _removeTime(t)),
              ActionChip(
                avatar: const Icon(Icons.add_rounded, size: 18),
                label: const Text('시각 추가'),
                onPressed: _pickTime,
              ),
            ],
          ),
          Gap.v24,
          FilledButton(
            onPressed: _saving ? null : _save,
            child: _saving
                ? const SizedBox(
                    height: 20,
                    width: 20,
                    child: CircularProgressIndicator(
                      strokeWidth: 2,
                      color: Colors.white,
                    ),
                  )
                : const Text('저장'),
          ),
        ],
      ),
    );
  }
}

/// "1회  [−] 1개 [+]" 한 줄. 값이 없으면 "모름"으로 보이고 +를 누르면 1부터 시작한다.
class _Stepper extends StatelessWidget {
  final String label;
  final String? value;
  final VoidCallback? onMinus;
  final VoidCallback? onPlus;
  const _Stepper({
    required this.label,
    required this.value,
    required this.onMinus,
    required this.onPlus,
  });

  @override
  Widget build(BuildContext context) {
    final muted = Theme.of(context).colorScheme.onSurfaceVariant;
    return Row(
      children: [
        SizedBox(width: 48, child: Text(label)),
        IconButton(
          icon: const Icon(Icons.remove_circle_outline_rounded),
          onPressed: onMinus,
          tooltip: '$label 줄이기',
        ),
        SizedBox(
          width: 64,
          child: Text(
            value ?? '모름',
            textAlign: TextAlign.center,
            style: TextStyle(
              fontWeight: FontWeight.w700,
              color: value == null ? muted : null,
            ),
          ),
        ),
        IconButton(
          icon: const Icon(Icons.add_circle_outline_rounded),
          onPressed: onPlus,
          tooltip: '$label 늘리기',
        ),
      ],
    );
  }
}
