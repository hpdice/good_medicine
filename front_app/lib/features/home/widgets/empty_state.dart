import 'package:flutter/material.dart';
import '../../../core/theme/app_theme.dart';

/// 복약함이 비어 있을 때 보여주는 안내 화면.
class EmptyState extends StatelessWidget {
  final VoidCallback onSearch;
  const EmptyState({super.key, required this.onSearch});

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          Icon(Icons.medication_outlined,
              size: 56, color: scheme.onSurfaceVariant),
          Gap.v16,
          Text('등록된 약이 없습니다',
              style: Theme.of(context).textTheme.titleMedium),
          Gap.v4,
          Text('검색하거나 처방전을 스캔해 약을 추가하면\n병용 위험을 확인해 드립니다.',
              textAlign: TextAlign.center,
              style: TextStyle(color: scheme.onSurfaceVariant, height: 1.5)),
          Gap.v24,
          FilledButton.icon(
            onPressed: onSearch,
            icon: const Icon(Icons.search_rounded, size: 18),
            label: const Text('약품 검색'),
            style: FilledButton.styleFrom(
                minimumSize: const Size(180, 48)),
          ),
        ]),
      ),
    );
  }
}
