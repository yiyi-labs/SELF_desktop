export interface ProductRecord {
  productId: string;
  brand: string;
  name: string;
  region: string;
  formulaVersion: string;
  specification: string;
  usageSummary: string;
  source: string;
  retrievedAt: string;
  evidenceType: string;
  materialRights: string;
  allowedViews: string[];
  calibrationProfile: string;
}
export class ProductRepository {
  // No invented SKU, efficacy, packaging or lip-product relationship.
  static records(): ProductRecord[] { return [{
    productId:'olay-us-super-serum-original-1oz-info-20260921',brand:'OLAY',name:'Super Serum',region:'美国官网',
    formulaVersion:'厂家未公开配方版本编号；本站快照不是配方认证',specification:'Original Size · 1 oz',
    usageSummary:'品牌用法摘要：清洁后使用精华，再使用保湿产品；白天使用防晒。请以所购包装说明为准。',
    source:'https://www.olay.com/products/super-serum',retrievedAt:'2026-09-21',evidenceType:'品牌公开资料；未独立验证功效',
    materialRights:'仅自主文字摘要；未取得包装图、实拍图的复用许可',allowedViews:['brand-information'],calibrationProfile:''
  }]; }
  static status(): string { return '品牌资料与数字编辑分开。本版没有 OLAY 功效标定，不能模拟该产品真实使用结果。'; }
}
