import { categoryClass } from "@/lib/notice-format";

// 입력: 분야, 출력: 분야 태그. 상세 창·캘린더가 같은 모양을 쓴다.
export function CategoryTag({ category }: { category: string }) {
  return <span className={`category-tag ${categoryClass(category)}`}>{category}</span>;
}
