import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';
import 'auth_provider.dart';

class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key});

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final _emailCtrl = TextEditingController();
  final _pwCtrl = TextEditingController();

  @override
  void dispose() {
    _emailCtrl.dispose();
    _pwCtrl.dispose();
    super.dispose();
  }

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
            child: LayoutBuilder(
              builder: (context, constraints) => SingleChildScrollView(
                padding: const EdgeInsets.all(24),
                child: ConstrainedBox(
                  constraints: BoxConstraints(minHeight: constraints.maxHeight - 48),
                  child: Column(
                    mainAxisAlignment: MainAxisAlignment.center,
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Text('약봉투 앱',
                          style: Theme.of(context).textTheme.headlineMedium),
                      const SizedBox(height: 32),
                      TextField(
                        controller: _emailCtrl,
                        decoration: const InputDecoration(
                            labelText: '이메일', border: OutlineInputBorder()),
                        keyboardType: TextInputType.emailAddress,
                      ),
                      const SizedBox(height: 12),
                      TextField(
                        controller: _pwCtrl,
                        decoration: const InputDecoration(
                            labelText: '비밀번호', border: OutlineInputBorder()),
                        obscureText: true,
                      ),
                      const SizedBox(height: 8),
                      if (auth.status == AuthStatus.error)
                        Padding(
                          padding: const EdgeInsets.only(bottom: 8),
                          child: Text(auth.errorMessage ?? '',
                              style: TextStyle(
                                  color: Theme.of(context).colorScheme.error,
                                  fontSize: 12)),
                        ),
                      const SizedBox(height: 16),
                      SizedBox(
                        width: double.infinity,
                        child: FilledButton(
                          onPressed: auth.status == AuthStatus.loading
                              ? null
                              : () => auth.login(_emailCtrl.text, _pwCtrl.text),
                          child: auth.status == AuthStatus.loading
                              ? const SizedBox(
                                  height: 20,
                                  width: 20,
                                  child: CircularProgressIndicator(strokeWidth: 2))
                              : const Text('로그인'),
                        ),
                      ),
                      TextButton(
                        onPressed: () => context.push('/register'),
                        child: const Text('회원가입'),
                      ),
                    ],
                  ),
                ),
              ),
            ),
          ),
        );
      },
    );
  }
}
