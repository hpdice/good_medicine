import 'package:flutter/material.dart';

enum StripTone { error, busy }

/// 화면 상단에 붙는 얇은 상태 배너(에러/작업 중).
class StripBanner extends StatelessWidget {
  final String text;
  final IconData? icon;
  final StripTone tone;
  final VoidCallback? onClose;

  const StripBanner(
      {super.key, required this.text, this.icon, required this.tone, this.onClose});

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final isErr = tone == StripTone.error;
    return Container(
      width: double.infinity,
      color: isErr ? scheme.errorContainer : scheme.surfaceContainerHighest,
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
      child: Row(children: [
        if (tone == StripTone.busy)
          const SizedBox(
              width: 14,
              height: 14,
              child: CircularProgressIndicator(strokeWidth: 2))
        else
          Icon(icon, size: 16, color: scheme.onErrorContainer),
        const SizedBox(width: 10),
        Expanded(
          child: Text(text,
              style: TextStyle(
                  fontSize: 13,
                  color:
                      isErr ? scheme.onErrorContainer : scheme.onSurfaceVariant)),
        ),
        if (onClose != null)
          TextButton(onPressed: onClose, child: const Text('닫기')),
      ]),
    );
  }
}
