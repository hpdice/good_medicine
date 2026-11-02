import 'package:flutter_test/flutter_test.dart';
import 'package:drugtest/core/models/analysis_models.dart';
import 'package:drugtest/core/models/drug_models.dart';
import 'package:drugtest/core/models/medicine_box_models.dart';

Map<String, dynamic> _entryJson(Map<String, dynamic> extra) => {
      'id': 'e1',
      'drug': {'id': 'd1', 'item_name': '테스트정'},
      'is_current': true,
      'added_method': 'manual',
      'created_at': '2026-11-03T00:00:00Z',
      ...extra,
    };

void main() {
  test('복약함 복용량은 둘 다 있을 때만 표시한다', () {
    final full = MedicineBoxEntry.fromJson(
        _entryJson({'units_per_intake': 0.5, 'times_per_day': 3}));
    expect(full.unitsPerIntake, 0.5);
    expect(full.doseLabel, '1회 0.5개 · 하루 3번');

    final whole = MedicineBoxEntry.fromJson(
        _entryJson({'units_per_intake': 2, 'times_per_day': 1}));
    expect(whole.doseLabel, '1회 2개 · 하루 1번'); // JSON 정수도 받는다

    final half = MedicineBoxEntry.fromJson(_entryJson({'times_per_day': 3}));
    expect(half.doseLabel, isNull);
  });

  test('약봉투에서 읽은 복용 안내는 읽은 항목만 복약함에 보낸다', () {
    final result = DrugNameMatchResult.fromJson({
      'queried_name': '신플랙스세이프정',
      'matched': null,
      'alternatives': [],
      'dose': {'units_per_intake': 1.0, 'times_per_day': 2, 'duration_days': 7},
    });
    expect(result.dose!.toBoxFields(), {
      'units_per_intake': 1.0,
      'times_per_day': 2,
      'intake_duration_days': 7,
    });

    // 횟수를 못 읽었으면 계산할 수 없으니 개수도 보내지 않는다
    final partial = OcrDose.fromJson({'units_per_intake': 1.0, 'duration_days': 7});
    expect(partial.toBoxFields(), {'intake_duration_days': 7});

    final noDose = DrugNameMatchResult.fromJson(
        {'queried_name': 'x', 'matched': null, 'alternatives': []});
    expect(noDose.dose, isNull);
  });

  test('판정 응답의 용량 초과 항목을 읽는다', () {
    final res = QuickCheckResponse.fromJson({
      'total_drugs': 2,
      'has_contraindication': false,
      'risk_level': 'caution',
      'contraindicated_count': 0,
      'dose_caution_count': 1,
      'findings': [],
      'dose_cautions': [
        {
          'drug_ids': ['d1', 'd2'],
          'drug_names': ['감기정', '해열정'],
          'ingredient': '아세트아미노펜',
          'daily_mg': 4950,
          'max_daily_mg': 4000.0,
          'scope': 'total',
          'uncounted_drug_names': ['기침시럽'],
        }
      ],
    });
    expect(res.doseCautionCount, 1);
    final d = res.doseCautions.single;
    expect(d.dailyMg, 4950.0);
    expect(d.drugIds, ['d1', 'd2']);
    expect(d.uncountedDrugNames, ['기침시럽']);
  });
}
