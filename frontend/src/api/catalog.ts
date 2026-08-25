/**
 * 目录/知识库配置与 LLM 配置 API。
 *
 * 对应后端：
 * - GET  /api/v1/catalog/*（public，仅启用态）
 * -      /api/v1/admin/catalog/*（管理员）
 * -      /api/v1/admin/source-priorities
 * -      /api/v1/admin/llm-config
 */
import { apiDelete, apiGet, apiPatch, apiPost, apiPut } from "./client";
import type { ApiList } from "../types/api";
import type {
  CatalogItem,
  DocumentType,
  ProductVersion,
  SourcePriority,
} from "../types/config";

// ---- 目录查询（public） ----
// signal 用于请求取消（组件卸载/切换条件时中止，DD-19 §4.4）。

export function listCatalogProducts(signal?: AbortSignal): Promise<ApiList<CatalogItem>> {
  return apiGet<ApiList<CatalogItem>>("/api/v1/catalog/products", signal);
}

export function listCatalogVersions(productId: string, signal?: AbortSignal): Promise<ApiList<ProductVersion>> {
  return apiGet<ApiList<ProductVersion>>(`/api/v1/catalog/products/${productId}/versions`, signal);
}

export function listCatalogDocumentTypes(signal?: AbortSignal): Promise<ApiList<DocumentType>> {
  return apiGet<ApiList<DocumentType>>("/api/v1/catalog/document-types", signal);
}

export function listCatalogProductForms(): Promise<ApiList<CatalogItem>> {
  return apiGet<ApiList<CatalogItem>>("/api/v1/catalog/product-forms");
}

export function listCatalogSourcePriorities(): Promise<ApiList<SourcePriority>> {
  return apiGet<ApiList<SourcePriority>>("/api/v1/catalog/source-priorities");
}

// ---- 管理员：产品 ----

export function adminListProducts(): Promise<ApiList<CatalogItem>> {
  return apiGet<ApiList<CatalogItem>>("/api/v1/admin/catalog/products");
}

export function adminCreateProduct(data: Partial<CatalogItem>): Promise<CatalogItem> {
  return apiPost<CatalogItem>("/api/v1/admin/catalog/products", data);
}

export function adminUpdateProduct(id: string, data: Record<string, unknown>): Promise<CatalogItem> {
  return apiPatch<CatalogItem>(`/api/v1/admin/catalog/products/${id}`, data);
}

export function adminSetProductStatus(id: string, status: "ENABLED" | "DISABLED"): Promise<CatalogItem> {
  return apiPost<CatalogItem>(`/api/v1/admin/catalog/products/${id}/${status === "ENABLED" ? "enable" : "disable"}`);
}

export function adminDeleteProduct(id: string): Promise<void> {
  return apiDelete<void>(`/api/v1/admin/catalog/products/${id}`);
}

// ---- 管理员：版本 ----

export function adminListVersions(productId: string): Promise<ApiList<ProductVersion>> {
  return apiGet<ApiList<ProductVersion>>(`/api/v1/admin/catalog/products/${productId}/versions`);
}

export function adminCreateVersion(productId: string, data: Record<string, unknown>): Promise<ProductVersion> {
  return apiPost<ProductVersion>(`/api/v1/admin/catalog/products/${productId}/versions`, data);
}

export function adminUpdateVersion(id: string, data: Record<string, unknown>): Promise<ProductVersion> {
  return apiPatch<ProductVersion>(`/api/v1/admin/catalog/versions/${id}`, data);
}

export function adminSetVersionStatus(id: string, status: "ENABLED" | "DISABLED"): Promise<ProductVersion> {
  return apiPost<ProductVersion>(`/api/v1/admin/catalog/versions/${id}/${status === "ENABLED" ? "enable" : "disable"}`);
}

export function adminDeleteVersion(id: string): Promise<void> {
  return apiDelete<void>(`/api/v1/admin/catalog/versions/${id}`);
}

// ---- 管理员：文档类型 ----

export function adminListDocumentTypes(): Promise<ApiList<DocumentType>> {
  return apiGet<ApiList<DocumentType>>("/api/v1/admin/catalog/document-types");
}

export function adminCreateDocumentType(data: Record<string, unknown>): Promise<DocumentType> {
  return apiPost<DocumentType>("/api/v1/admin/catalog/document-types", data);
}

export function adminUpdateDocumentType(id: string, data: Record<string, unknown>): Promise<DocumentType> {
  return apiPatch<DocumentType>(`/api/v1/admin/catalog/document-types/${id}`, data);
}

export function adminSetDocumentTypeStatus(id: string, status: "ENABLED" | "DISABLED"): Promise<DocumentType> {
  return apiPost<DocumentType>(`/api/v1/admin/catalog/document-types/${id}/${status === "ENABLED" ? "enable" : "disable"}`);
}

export function adminDeleteDocumentType(id: string): Promise<void> {
  return apiDelete<void>(`/api/v1/admin/catalog/document-types/${id}`);
}

// ---- 管理员：产品形态 ----

export function adminListProductForms(): Promise<ApiList<CatalogItem>> {
  return apiGet<ApiList<CatalogItem>>("/api/v1/admin/catalog/product-forms");
}

export function adminCreateProductForm(data: Record<string, unknown>): Promise<CatalogItem> {
  return apiPost<CatalogItem>("/api/v1/admin/catalog/product-forms", data);
}

export function adminUpdateProductForm(id: string, data: Record<string, unknown>): Promise<CatalogItem> {
  return apiPatch<CatalogItem>(`/api/v1/admin/catalog/product-forms/${id}`, data);
}

export function adminSetProductFormStatus(id: string, status: "ENABLED" | "DISABLED"): Promise<CatalogItem> {
  return apiPost<CatalogItem>(`/api/v1/admin/catalog/product-forms/${id}/${status === "ENABLED" ? "enable" : "disable"}`);
}

export function adminDeleteProductForm(id: string): Promise<void> {
  return apiDelete<void>(`/api/v1/admin/catalog/product-forms/${id}`);
}

// ---- 来源优先级 ----

export function adminListSourcePriorities(): Promise<ApiList<SourcePriority>> {
  return apiGet<ApiList<SourcePriority>>("/api/v1/admin/source-priorities");
}

export function adminUpdateSourcePriorities(
  items: Array<{ source_code: string; priority: number }>,
): Promise<ApiList<SourcePriority>> {
  return apiPatch<ApiList<SourcePriority>>("/api/v1/admin/source-priorities", { items });
}
