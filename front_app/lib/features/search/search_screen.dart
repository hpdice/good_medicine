import 'dart:async';
import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';
import '../../core/models/drug_models.dart';
import '../../core/theme/app_theme.dart';
import 'search_provider.dart';

class SearchScreen extends StatefulWidget {
  const SearchScreen({super.key});

  @override
  State<SearchScreen> createState() => _SearchScreenState();
}

class _SearchScreenState extends State<SearchScreen> {
  final _ctrl = TextEditingController();
  Timer? _debounce;

  @override
  void dispose() {
    _ctrl.dispose();
    _debounce?.cancel();
    super.dispose();
  }

  void _onChanged(String q, SearchProvider search) {
    search.updateQuery(q);
    _debounce?.cancel();
    _debounce = Timer(const Duration(milliseconds: 300), () => search.search(q));
  }

  @override
  Widget build(BuildContext context) {
    return Consumer<SearchProvider>(builder: (context, search, _) {
      if (search.addSuccess) {
        WidgetsBinding.instance.addPostFrameCallback((_) {
          search.resetAddSuccess();
          context.go('/');
        });
      }
      return Scaffold(
        appBar: AppBar(title: const Text('약품 검색')),
        body: Column(children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 4, 16, 12),
            child: TextField(
              controller: _ctrl,
              autofocus: true,
              textInputAction: TextInputAction.search,
              decoration: InputDecoration(
                hintText: '약품명을 입력하세요',
                prefixIcon: const Icon(Icons.search_rounded),
                suffixIcon: _ctrl.text.isEmpty
                    ? null
                    : IconButton(
                        icon: const Icon(Icons.close_rounded, size: 20),
                        onPressed: () {
                          _ctrl.clear();
                          _onChanged('', search);
                          setState(() {});
                        },
                      ),
              ),
              onChanged: (q) {
                _onChanged(q, search);
                setState(() {});
              },
            ),
          ),
          Expanded(child: _buildResults(context, search)),
        ]),
      );
    });
  }

  Widget _buildResults(BuildContext context, SearchProvider search) {
    if (search.isLoading) {
      return const Center(child: CircularProgressIndicator());
    }
    if (search.error != null) {
      return _CenterMessage(
        icon: Icons.wifi_off_rounded,
        title: search.error!,
        action: TextButton(
            onPressed: search.clearError, child: const Text('닫기')),
      );
    }
    if (search.query.isEmpty) {
      return _CenterMessage(
        icon: Icons.search_rounded,
        title: '약품명으로 검색',
        subtitle: '예: 타이레놀, 아스피린, 와파린정',
      );
    }
    if (search.results.isEmpty) {
      return const _CenterMessage(
        icon: Icons.search_off_rounded,
        title: '검색 결과가 없습니다',
        subtitle: '철자를 확인하거나 다른 이름으로 시도해 보세요.',
      );
    }
    return ListView.separated(
      padding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
      itemCount: search.results.length,
      separatorBuilder: (_, __) => const SizedBox(height: 10),
      itemBuilder: (context, i) {
        final drug = search.results[i];
        return _DrugCard(
          drug: drug,
          onTap: () => _showDetail(context, drug, search),
        );
      },
    );
  }

  void _showDetail(
      BuildContext context, DrugSearchResult drug, SearchProvider search) {
    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      builder: (_) => DraggableScrollableSheet(
        expand: false,
        initialChildSize: 0.5,
        maxChildSize: 0.9,
        builder: (_, ctrl) => ListView(
          controller: ctrl,
          padding: const EdgeInsets.fromLTRB(20, 4, 20, 28),
          children: [
            Text(drug.displayName,
                style: Theme.of(context)
                    .textTheme
                    .titleLarge
                    ?.copyWith(fontWeight: FontWeight.w700)),
            if (drug.entpName != null) ...[
              const SizedBox(height: 4),
              Text(drug.entpName!,
                  style: TextStyle(
                      fontSize: 13,
                      color: Theme.of(context).colorScheme.onSurfaceVariant)),
            ],
            _InfoSection(label: '효능', text: drug.efcyQesitm),
            Gap.v24,
            FilledButton.icon(
              onPressed: () {
                context.pop();
                search.addToBox(drug.id);
              },
              icon: const Icon(Icons.add_rounded, size: 20),
              label: const Text('내 약에 추가'),
            ),
          ],
        ),
      ),
    );
  }
}

class _InfoSection extends StatelessWidget {
  final String label;
  final String? text;
  const _InfoSection({required this.label, required this.text});

  @override
  Widget build(BuildContext context) {
    if (text == null || text!.isEmpty) return const SizedBox.shrink();
    return Padding(
      padding: const EdgeInsets.only(top: 16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _SectionLabel(label),
          const SizedBox(height: 4),
          Text(text!, style: const TextStyle(height: 1.5)),
        ],
      ),
    );
  }
}

class _SectionLabel extends StatelessWidget {
  final String text;
  const _SectionLabel(this.text);
  @override
  Widget build(BuildContext context) => Text(text,
      style: TextStyle(
          fontWeight: FontWeight.w700,
          fontSize: 13,
          color: Theme.of(context).colorScheme.primary));
}

class _CenterMessage extends StatelessWidget {
  final IconData icon;
  final String title;
  final String? subtitle;
  final Widget? action;
  const _CenterMessage(
      {required this.icon, required this.title, this.subtitle, this.action});

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          Icon(icon, size: 48, color: scheme.onSurfaceVariant),
          Gap.v12,
          Text(title,
              textAlign: TextAlign.center,
              style: Theme.of(context).textTheme.titleMedium),
          if (subtitle != null) ...[
            Gap.v4,
            Text(subtitle!,
                textAlign: TextAlign.center,
                style: TextStyle(color: scheme.onSurfaceVariant)),
          ],
          if (action != null) ...[Gap.v8, action!],
        ]),
      ),
    );
  }
}

class _DrugCard extends StatelessWidget {
  final DrugSearchResult drug;
  final VoidCallback onTap;
  const _DrugCard({required this.drug, required this.onTap});

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final meta = [drug.className, drug.etcOtcName]
        .where((e) => e != null && e.isNotEmpty)
        .join('  ·  ');
    return Card(
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(kRadius),
        child: Padding(
          padding: const EdgeInsets.all(14),
          child: Row(children: [
            Expanded(
              child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(drug.displayName,
                        style: const TextStyle(
                            fontWeight: FontWeight.w700, fontSize: 14.5)),
                    if (meta.isNotEmpty) ...[
                      const SizedBox(height: 3),
                      Text(meta,
                          style: TextStyle(
                              fontSize: 12, color: scheme.onSurfaceVariant)),
                    ],
                    if (drug.entpName != null) ...[
                      const SizedBox(height: 1),
                      Text(drug.entpName!,
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: TextStyle(
                              fontSize: 11.5, color: scheme.onSurfaceVariant)),
                    ],
                  ]),
            ),
            Icon(Icons.chevron_right_rounded, color: scheme.onSurfaceVariant),
          ]),
        ),
      ),
    );
  }
}
