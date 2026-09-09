import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:image_picker/image_picker.dart';
import 'package:provider/provider.dart';
import '../../core/theme/app_theme.dart';
import 'camera_provider.dart';

/// 처방전·약봉투 사진을 촬영하거나 파일에서 골라 서버 OCR로 보낸다.
/// (온디바이스 카메라 프리뷰 대신 image_picker — 웹 포함 전 플랫폼 동일 동작)
class CameraScreen extends StatefulWidget {
  const CameraScreen({super.key});

  @override
  State<CameraScreen> createState() => _CameraScreenState();
}

class _CameraScreenState extends State<CameraScreen> {
  final _picker = ImagePicker();
  bool _busy = false;

  Future<void> _pick(ImageSource source) async {
    if (_busy) return;
    setState(() => _busy = true);
    try {
      final XFile? file = await _picker.pickImage(
        source: source,
        maxWidth: 2000,
        imageQuality: 85,
      );
      if (file == null || !mounted) return;
      final bytes = await file.readAsBytes();
      if (!mounted) return;
      await context
          .read<CameraProvider>()
          .processImageBytes(bytes, filename: file.name);
      if (mounted) context.push('/ocr-result');
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text('이미지를 불러오지 못했습니다: $e')));
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  void _viewPhoto(SubmittedPhoto p) {
    showDialog<void>(
      context: context,
      builder: (_) => Dialog(
        child: InteractiveViewer(
          child: Image.memory(p.bytes, fit: BoxFit.contain),
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final cam = context.watch<CameraProvider>();
    final scheme = Theme.of(context).colorScheme;
    final busy = _busy || cam.isProcessing;

    return Scaffold(
      appBar: AppBar(title: const Text('처방전 스캔')),
      body: ListView(
        padding: kScreenPadding,
        children: [
          Container(
            padding: const EdgeInsets.all(16),
            decoration: softCard(context),
            child: Row(children: [
              Container(
                padding: const EdgeInsets.all(8),
                decoration: BoxDecoration(
                  color: scheme.primary.withValues(alpha: 0.12),
                  shape: BoxShape.circle,
                ),
                child: Icon(Icons.privacy_tip_outlined,
                    size: 18, color: scheme.primary),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Text(
                  '사진은 서버에서 약품명만 인식한 뒤 즉시 삭제됩니다.\n'
                  '원본은 서버에 저장되지 않고, 이 화면에서만 잠시 볼 수 있어요.',
                  style: TextStyle(
                      fontSize: 12.5,
                      height: 1.45,
                      color: scheme.onSurfaceVariant),
                ),
              ),
            ]),
          ),
          Gap.v16,
          if (!kIsWeb) ...[
            FilledButton.icon(
              onPressed: busy ? null : () => _pick(ImageSource.camera),
              icon: const Icon(Icons.photo_camera_rounded),
              label: const Text('사진 촬영'),
            ),
            Gap.v12,
          ],
          OutlinedButton.icon(
            onPressed: busy ? null : () => _pick(ImageSource.gallery),
            icon: const Icon(Icons.photo_library_outlined),
            label: Text(kIsWeb ? '이미지 선택' : '앨범에서 선택'),
          ),
          if (busy) ...[
            Gap.v24,
            const Center(child: CircularProgressIndicator()),
            Gap.v8,
            Center(
                child: Text('사진에서 약품을 인식하는 중…',
                    style: TextStyle(color: scheme.onSurfaceVariant))),
          ],
          if (cam.history.isNotEmpty) ...[
            Gap.v32,
            Row(
              children: [
                Text('최근 올린 사진',
                    style: Theme.of(context).textTheme.titleSmall),
                const SizedBox(width: 8),
                Text('앱을 닫으면 사라져요',
                    style: TextStyle(
                        fontSize: 12, color: scheme.onSurfaceVariant)),
              ],
            ),
            Gap.v12,
            GridView.count(
              crossAxisCount: 3,
              shrinkWrap: true,
              physics: const NeverScrollableScrollPhysics(),
              mainAxisSpacing: 8,
              crossAxisSpacing: 8,
              children: [
                for (final p in cam.history)
                  InkWell(
                    onTap: () => _viewPhoto(p),
                    child: Stack(
                      fit: StackFit.expand,
                      children: [
                        ClipRRect(
                          borderRadius: BorderRadius.circular(8),
                          child: Image.memory(p.bytes, fit: BoxFit.cover),
                        ),
                        Positioned(
                          left: 0,
                          right: 0,
                          bottom: 0,
                          child: Container(
                            color: Colors.black54,
                            padding: const EdgeInsets.symmetric(vertical: 2),
                            child: Text(
                              '매칭 ${p.matchedCount}/${p.candidateCount}',
                              textAlign: TextAlign.center,
                              style: const TextStyle(
                                  color: Colors.white, fontSize: 11),
                            ),
                          ),
                        ),
                      ],
                    ),
                  ),
              ],
            ),
          ],
        ],
      ),
    );
  }
}
