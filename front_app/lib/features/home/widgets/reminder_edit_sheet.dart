import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../../../core/models/medicine_box_models.dart';
import '../../../core/theme/app_theme.dart';
import '../home_provider.dart';

Future<void> showReminderEditSheet(BuildContext context, MedicineBoxEntry entry) {
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

class _ReminderEditSheetState extends State<_ReminderEditSheet> {
  late List<String> _times;
  late bool _enabled;
  bool _saving = false;

  @override
  void initState() {
    super.initState();
    _times = [...widget.entry.intakeTimes]..sort();
    _enabled = widget.entry.reminderEnabled;
  }

  Future<void> _pickTime() async {
    final picked = await showTimePicker(context: context, initialTime: TimeOfDay.now());
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
    final ok = await home.updateEntry(widget.entry.id, {
      'intake_times': _times,
      'reminder_enabled': _enabled,
    });
    if (!mounted) return;
    if (ok) {
      Navigator.of(context).pop();
    } else {
      setState(() => _saving = false);
      ScaffoldMessenger.of(context)
          .showSnackBar(const SnackBar(content: Text('저장에 실패했습니다.')));
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
          Text('복약 알림',
              style: Theme.of(context)
                  .textTheme
                  .titleLarge
                  ?.copyWith(fontWeight: FontWeight.w700)),
          Gap.v4,
          Text(widget.entry.drug.displayName,
              style: TextStyle(color: scheme.onSurfaceVariant)),
          Gap.v16,
          SwitchListTile(
            contentPadding: EdgeInsets.zero,
            title: const Text('알림 켜기'),
            subtitle: const Text('매일 아래 시각에 이 약 복용을 알려줍니다'),
            value: _enabled,
            onChanged: (v) => setState(() => _enabled = v),
          ),
          Gap.v8,
          Wrap(spacing: 8, runSpacing: 8, children: [
            for (final t in _times)
              Chip(label: Text(t), onDeleted: () => _removeTime(t)),
            ActionChip(
              avatar: const Icon(Icons.add_rounded, size: 18),
              label: const Text('시각 추가'),
              onPressed: _pickTime,
            ),
          ]),
          Gap.v24,
          FilledButton(
            onPressed: _saving ? null : _save,
            child: _saving
                ? const SizedBox(
                    height: 20,
                    width: 20,
                    child: CircularProgressIndicator(
                        strokeWidth: 2, color: Colors.white))
                : const Text('저장'),
          ),
        ],
      ),
    );
  }
}
