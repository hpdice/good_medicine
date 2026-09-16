import 'package:flutter/material.dart';

/// 목록 위에 떠 있는 닫을 수 있는 에러 배너.
class FloatingError extends StatelessWidget {
  final String text;
  final VoidCallback onClose;
  const FloatingError({super.key, required this.text, required this.onClose});

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Material(
      elevation: 3,
      borderRadius: BorderRadius.circular(12),
      color: scheme.errorContainer,
      child: Padding(
        padding: const EdgeInsets.fromLTRB(16, 6, 8, 6),
        child: Row(children: [
          Expanded(
              child: Text(text,
                  style: TextStyle(color: scheme.onErrorContainer))),
          TextButton(onPressed: onClose, child: const Text('닫기')),
        ]),
      ),
    );
  }
}
