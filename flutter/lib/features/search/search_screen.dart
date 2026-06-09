import 'dart:async';
import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';
import '../../core/models/drug_models.dart';
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
            padding: const EdgeInsets.all(16),
            child: TextField(
              controller: _ctrl,
              autofocus: true,
              decoration: InputDecoration(
                hintText: '약품명 검색...',
                prefixIcon: const Icon(Icons.search),
                border: OutlineInputBorder(
                    borderRadius: BorderRadius.circular(12)),
              ),
              onChanged: (q) => _onChanged(q, search),
            ),
          ),
          Expanded(child: _buildResults(context, search)),
        ]),
      );
    });
  }

  Widget _buildResults(BuildContext context, SearchProvider search) {
    if (search.isLoading) return const Center(child: CircularProgressIndicator());
    if (search.results.isEmpty && search.query.isNotEmpty) {
      return const Center(child: Text('검색 결과가 없습니다.'));
    }
    return ListView.separated(
      padding: const EdgeInsets.symmetric(horizontal: 16),
      itemCount: search.results.length,
      separatorBuilder: (_, __) => const SizedBox(height: 8),
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
      shape: const RoundedRectangleBorder(
          borderRadius: BorderRadius.vertical(top: Radius.circular(16))),
      builder: (_) => DraggableScrollableSheet(
        expand: false,
        initialChildSize: 0.5,
        maxChildSize: 0.9,
        builder: (_, ctrl) => ListView(
          controller: ctrl,
          padding: const EdgeInsets.all(20),
          children: [
            Text(drug.itemName,
                style: Theme.of(context).textTheme.titleLarge?.copyWith(
                    fontWeight: FontWeight.bold)),
            const SizedBox(height: 12),
            Text('효능',
                style: TextStyle(
                    fontWeight: FontWeight.w600,
                    color: Theme.of(context).colorScheme.primary)),
            const SizedBox(height: 4),
            Text(drug.efcyQesitm ?? '효능 정보 없음'),
            const SizedBox(height: 20),
            SizedBox(
              width: double.infinity,
              child: FilledButton(
                onPressed: () {
                  context.pop();
                  search.addToBox(drug.id);
                },
                child: const Text('+ 내 약에 추가'),
              ),
            ),
            const SizedBox(height: 8),
          ],
        ),
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
    return Card(
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(12),
        child: Padding(
          padding: const EdgeInsets.all(12),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(drug.itemName,
                style: const TextStyle(fontWeight: FontWeight.w500)),
            const SizedBox(height: 4),
            Row(children: [
              if (drug.className != null)
                Text(drug.className!,
                    style:
                        TextStyle(fontSize: 12, color: Colors.grey.shade600)),
              if (drug.className != null && drug.etcOtcName != null)
                Text(' | ',
                    style:
                        TextStyle(fontSize: 12, color: Colors.grey.shade600)),
              if (drug.etcOtcName != null)
                Text(drug.etcOtcName!,
                    style:
                        TextStyle(fontSize: 12, color: Colors.grey.shade600)),
            ]),
            if (drug.entpName != null)
              Text(drug.entpName!,
                  style: TextStyle(fontSize: 12, color: Colors.grey.shade600)),
          ]),
        ),
      ),
    );
  }
}
