import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';
import 'auth_provider.dart';

class RegisterScreen extends StatefulWidget {
  const RegisterScreen({super.key});

  @override
  State<RegisterScreen> createState() => _RegisterScreenState();
}

class _RegisterScreenState extends State<RegisterScreen> {
  final _nameCtrl = TextEditingController();
  final _emailCtrl = TextEditingController();
  final _pwCtrl = TextEditingController();
  bool _privacyConsent = false;
  bool _healthConsent = false;

  @override
  void dispose() {
    _nameCtrl.dispose();
    _emailCtrl.dispose();
    _pwCtrl.dispose();
    super.dispose();
  }

  bool get _canSubmit =>
      _nameCtrl.text.isNotEmpty &&
      _emailCtrl.text.isNotEmpty &&
      _pwCtrl.text.length >= 8 &&
      _privacyConsent &&
      _healthConsent;

  @override
  Widget build(BuildContext context) {
    return Consumer<AuthProvider>(
      builder: (context, auth, _) {
        if (auth.status == AuthStatus.success) {
          WidgetsBinding.instance.addPostFrameCallback((_) {
            auth.resetState();
            context.go('/');
          });
        }
        return Scaffold(
          body: SafeArea(
            child: SingleChildScrollView(
              padding: const EdgeInsets.all(24),
              child: Column(
                children: [
                  const SizedBox(height: 32),
                  Text('회원가입',
                      style: Theme.of(context).textTheme.headlineMedium),
                  const SizedBox(height: 32),
                  TextField(
                    controller: _nameCtrl,
                    decoration: const InputDecoration(
                        labelText: '이름', border: OutlineInputBorder()),
                    onChanged: (_) => setState(() {}),
                  ),
                  const SizedBox(height: 12),
                  TextField(
                    controller: _emailCtrl,
                    decoration: const InputDecoration(
                        labelText: '이메일', border: OutlineInputBorder()),
                    keyboardType: TextInputType.emailAddress,
                    onChanged: (_) => setState(() {}),
                  ),
                  const SizedBox(height: 12),
                  TextField(
                    controller: _pwCtrl,
                    decoration: const InputDecoration(
                        labelText: '비밀번호 (최소 8자)',
                        border: OutlineInputBorder()),
                    obscureText: true,
                    onChanged: (_) => setState(() {}),
                  ),
                  const SizedBox(height: 16),
                  CheckboxListTile(
                    value: _privacyConsent,
                    onChanged: (v) => setState(() => _privacyConsent = v!),
                    title: const Text('개인정보 수집 및 이용 동의 (필수)'),
                    controlAffinity: ListTileControlAffinity.leading,
                    contentPadding: EdgeInsets.zero,
                  ),
                  CheckboxListTile(
                    value: _healthConsent,
                    onChanged: (v) => setState(() => _healthConsent = v!),
                    title: const Text('건강 정보 처리 동의 (필수)'),
                    controlAffinity: ListTileControlAffinity.leading,
                    contentPadding: EdgeInsets.zero,
                  ),
                  if (auth.status == AuthStatus.error)
                    Padding(
                      padding: const EdgeInsets.only(bottom: 8),
                      child: Text(auth.errorMessage ?? '',
                          style: TextStyle(
                              color: Theme.of(context).colorScheme.error,
                              fontSize: 12)),
                    ),
                  const SizedBox(height: 8),
                  SizedBox(
                    width: double.infinity,
                    child: FilledButton(
                      onPressed: auth.status == AuthStatus.loading || !_canSubmit
                          ? null
                          : () => auth.register(
                              _emailCtrl.text, _pwCtrl.text, _nameCtrl.text),
                      child: auth.status == AuthStatus.loading
                          ? const SizedBox(
                              height: 20,
                              width: 20,
                              child: CircularProgressIndicator(strokeWidth: 2))
                          : const Text('회원가입'),
                    ),
                  ),
                  TextButton(
                    onPressed: () => context.pop(),
                    child: const Text('로그인으로 돌아가기'),
                  ),
                ],
              ),
            ),
          ),
        );
      },
    );
  }
}
