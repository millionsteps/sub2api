package admin

import (
	"context"
	"fmt"
	"path/filepath"
	"sort"
	"strings"

	"github.com/Wei-Shaw/sub2api/internal/pkg/response"
	"github.com/Wei-Shaw/sub2api/internal/service"
	"github.com/gin-gonic/gin"
)

var knownCodexPlanSuffixes = map[string]struct{}{
	"plus":       {},
	"pro":        {},
	"free":       {},
	"team":       {},
	"enterprise": {},
	"business":   {},
	"edu":        {},
	"personal":   {},
}

type deleteAccountsByFileNamesRequest struct {
	FileNames []string `json:"file_names" binding:"required,min=1"`
	DryRun    bool     `json:"dry_run"`
}

type getAccountsByFileNamesRequest struct {
	FileNames []string `json:"file_names" binding:"required,min=1"`
}

type replaceAccountsByFileNamesRequest struct {
	FileNames            []string    `json:"file_names" binding:"required,min=1"`
	Data                 DataPayload `json:"data" binding:"required"`
	SkipDefaultGroupBind *bool       `json:"skip_default_group_bind"`
}

type matchedAccountSummary struct {
	ID       int64  `json:"id"`
	Name     string `json:"name"`
	Platform string `json:"platform"`
	Type     string `json:"type"`
}

type deleteAccountsByFileNameResult struct {
	FileName          string                  `json:"file_name"`
	Platform          string                  `json:"platform,omitempty"`
	Type              string                  `json:"type,omitempty"`
	CandidateNames    []string                `json:"candidate_names,omitempty"`
	MatchedAccountIDs []int64                 `json:"matched_account_ids,omitempty"`
	MatchedAccounts   []matchedAccountSummary `json:"matched_accounts,omitempty"`
	DeletedAccountIDs []int64                 `json:"deleted_account_ids,omitempty"`
	Error             string                  `json:"error,omitempty"`
}

type deleteAccountsByFileNamesResponse struct {
	RequestedFiles  int                              `json:"requested_files"`
	MatchedFiles    int                              `json:"matched_files"`
	DeletedAccounts int                              `json:"deleted_accounts"`
	NotFoundFiles   int                              `json:"not_found_files"`
	DryRun          bool                             `json:"dry_run"`
	Results         []deleteAccountsByFileNameResult `json:"results"`
}

type credentialFileDeleteSpec struct {
	FileName       string
	Platform       string
	Type           string
	CandidateNames []string
}

type accountFileMatchesResult struct {
	RequestedFiles int                              `json:"requested_files"`
	MatchedFiles   int                              `json:"matched_files"`
	NotFoundFiles  int                              `json:"not_found_files"`
	Results        []deleteAccountsByFileNameResult `json:"results"`
}

type replaceAccountsByFileNamesResponse struct {
	RequestedFiles  int                              `json:"requested_files"`
	MatchedFiles    int                              `json:"matched_files"`
	DeletedAccounts int                              `json:"deleted_accounts"`
	NotFoundFiles   int                              `json:"not_found_files"`
	ProxyCreated    int                              `json:"proxy_created"`
	ProxyReused     int                              `json:"proxy_reused"`
	ProxyFailed     int                              `json:"proxy_failed"`
	AccountCreated  int                              `json:"account_created"`
	AccountFailed   int                              `json:"account_failed"`
	Results         []deleteAccountsByFileNameResult `json:"results,omitempty"`
	Errors          []DataImportError                `json:"errors,omitempty"`
}

// GetByFileNames 按凭证文件名查询远程账号。
// POST /api/v1/admin/accounts/get-by-file-names
func (h *AccountHandler) GetByFileNames(c *gin.Context) {
	var req getAccountsByFileNamesRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		response.BadRequest(c, "Invalid request: "+err.Error())
		return
	}

	result, err := h.queryAccountsByFileNames(c.Request.Context(), req.FileNames)
	if err != nil {
		response.ErrorFrom(c, err)
		return
	}
	response.Success(c, result)
}

// DeleteByFileNames 按凭证文件名删除远程账号。
// POST /api/v1/admin/accounts/delete-by-file-names
func (h *AccountHandler) DeleteByFileNames(c *gin.Context) {
	var req deleteAccountsByFileNamesRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		response.BadRequest(c, "Invalid request: "+err.Error())
		return
	}

	executeAdminIdempotentJSON(
		c,
		"admin.accounts.delete_by_file_names",
		req,
		service.DefaultWriteIdempotencyTTL(),
		func(ctx context.Context) (any, error) {
			return h.deleteAccountsByFileNames(ctx, req)
		},
	)
}

func (h *AccountHandler) deleteAccountsByFileNames(
	ctx context.Context,
	req deleteAccountsByFileNamesRequest,
) (deleteAccountsByFileNamesResponse, error) {
	matchResult, err := h.queryAccountsByFileNames(ctx, req.FileNames)
	if err != nil {
		return deleteAccountsByFileNamesResponse{}, err
	}

	out := deleteAccountsByFileNamesResponse{
		RequestedFiles: matchResult.RequestedFiles,
		MatchedFiles:   matchResult.MatchedFiles,
		NotFoundFiles:  matchResult.NotFoundFiles,
		DryRun:         req.DryRun,
		Results:        matchResult.Results,
	}

	if req.DryRun {
		return out, nil
	}

	for i := range out.Results {
		result := &out.Results[i]
		if result.Error != "" || len(result.MatchedAccounts) == 0 {
			continue
		}
		for _, account := range result.MatchedAccounts {
			if err := h.adminService.DeleteAccount(ctx, account.ID); err != nil {
				result.Error = err.Error()
				break
			}
			result.DeletedAccountIDs = append(result.DeletedAccountIDs, account.ID)
			out.DeletedAccounts++
		}
	}

	return out, nil
}

// ReplaceByFileNames 按文件名先删除再导入账号。
// POST /api/v1/admin/accounts/replace-by-file-names
func (h *AccountHandler) ReplaceByFileNames(c *gin.Context) {
	var req replaceAccountsByFileNamesRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		response.BadRequest(c, "Invalid request: "+err.Error())
		return
	}
	if err := validateDataHeader(req.Data); err != nil {
		response.BadRequest(c, err.Error())
		return
	}
	if err := validateDataPayloadItems(req.Data); err != nil {
		response.BadRequest(c, err.Error())
		return
	}

	executeAdminIdempotentJSON(
		c,
		"admin.accounts.replace_by_file_names",
		req,
		service.DefaultWriteIdempotencyTTL(),
		func(ctx context.Context) (any, error) {
			return h.replaceAccountsByFileNames(ctx, req)
		},
	)
}

func (h *AccountHandler) replaceAccountsByFileNames(
	ctx context.Context,
	req replaceAccountsByFileNamesRequest,
) (replaceAccountsByFileNamesResponse, error) {
	deleteResult, err := h.deleteAccountsByFileNames(ctx, deleteAccountsByFileNamesRequest{
		FileNames: req.FileNames,
		DryRun:    false,
	})
	if err != nil {
		return replaceAccountsByFileNamesResponse{}, err
	}

	importResult, err := h.importData(ctx, DataImportRequest{
		Data:                 req.Data,
		SkipDefaultGroupBind: req.SkipDefaultGroupBind,
	})
	if err != nil {
		return replaceAccountsByFileNamesResponse{}, err
	}

	return replaceAccountsByFileNamesResponse{
		RequestedFiles:  deleteResult.RequestedFiles,
		MatchedFiles:    deleteResult.MatchedFiles,
		DeletedAccounts: deleteResult.DeletedAccounts,
		NotFoundFiles:   deleteResult.NotFoundFiles,
		ProxyCreated:    importResult.ProxyCreated,
		ProxyReused:     importResult.ProxyReused,
		ProxyFailed:     importResult.ProxyFailed,
		AccountCreated:  importResult.AccountCreated,
		AccountFailed:   importResult.AccountFailed,
		Results:         deleteResult.Results,
		Errors:          importResult.Errors,
	}, nil
}

func (h *AccountHandler) queryAccountsByFileNames(
	ctx context.Context,
	fileNames []string,
) (accountFileMatchesResult, error) {
	out := accountFileMatchesResult{
		RequestedFiles: len(fileNames),
		Results:        make([]deleteAccountsByFileNameResult, 0, len(fileNames)),
	}

	accountCache := make(map[string][]service.Account)
	for _, rawFileName := range fileNames {
		result := deleteAccountsByFileNameResult{FileName: normalizeCredentialFileName(rawFileName)}
		spec, err := buildCredentialFileDeleteSpec(rawFileName)
		if err != nil {
			result.Error = err.Error()
			out.NotFoundFiles++
			out.Results = append(out.Results, result)
			continue
		}

		result.Platform = spec.Platform
		result.Type = spec.Type
		result.CandidateNames = spec.CandidateNames

		cacheKey := spec.Platform + "|" + spec.Type
		accounts, ok := accountCache[cacheKey]
		if !ok {
			accounts, err = h.listAccountsFiltered(ctx, spec.Platform, spec.Type, "", "")
			if err != nil {
				return out, err
			}
			accountCache[cacheKey] = accounts
		}

		matchedAccounts := matchAccountsByCandidateNames(accounts, spec.CandidateNames)
		if len(matchedAccounts) == 0 {
			out.NotFoundFiles++
			out.Results = append(out.Results, result)
			continue
		}

		out.MatchedFiles++
		for _, account := range matchedAccounts {
			result.MatchedAccountIDs = append(result.MatchedAccountIDs, account.ID)
			result.MatchedAccounts = append(result.MatchedAccounts, matchedAccountSummary{
				ID:       account.ID,
				Name:     account.Name,
				Platform: account.Platform,
				Type:     account.Type,
			})
		}
		sort.Slice(result.MatchedAccountIDs, func(i, j int) bool {
			return result.MatchedAccountIDs[i] < result.MatchedAccountIDs[j]
		})
		sort.Slice(result.MatchedAccounts, func(i, j int) bool {
			return result.MatchedAccounts[i].ID < result.MatchedAccounts[j].ID
		})
		out.Results = append(out.Results, result)
	}

	return out, nil
}

func buildCredentialFileDeleteSpec(fileName string) (credentialFileDeleteSpec, error) {
	normalized := normalizeCredentialFileName(fileName)
	if normalized == "" {
		return credentialFileDeleteSpec{}, fmt.Errorf("file_name is required")
	}

	stem := strings.TrimSuffix(normalized, filepath.Ext(normalized))
	if stem == "" {
		return credentialFileDeleteSpec{}, fmt.Errorf("file_name is invalid: %s", normalized)
	}

	if strings.HasPrefix(stem, "antigravity-") {
		return credentialFileDeleteSpec{
			FileName:       normalized,
			Platform:       service.PlatformAntigravity,
			Type:           service.AccountTypeOAuth,
			CandidateNames: []string{stem},
		}, nil
	}

	candidates := buildCodexCandidateNames(stem)
	if len(candidates) == 0 {
		return credentialFileDeleteSpec{}, fmt.Errorf("unsupported credential file name: %s", normalized)
	}

	return credentialFileDeleteSpec{
		FileName:       normalized,
		Platform:       service.PlatformOpenAI,
		Type:           service.AccountTypeOAuth,
		CandidateNames: candidates,
	}, nil
}

func buildCodexCandidateNames(stem string) []string {
	candidateSet := make(map[string]struct{})

	addCandidate := func(name string) {
		name = strings.TrimSpace(name)
		if name == "" {
			return
		}
		candidateSet[name] = struct{}{}
	}

	if strings.HasPrefix(stem, "codex-") {
		addCandidate(stem)
		remainder := strings.TrimPrefix(stem, "codex-")
		emailCandidate := parseCodexEmailCandidate(remainder)
		if emailCandidate != "" {
			addCandidate("codex-" + emailCandidate)
		}
	} else {
		addCandidate("codex-" + stem)
	}

	candidates := make([]string, 0, len(candidateSet))
	for candidate := range candidateSet {
		candidates = append(candidates, candidate)
	}
	sort.Strings(candidates)
	return candidates
}

func parseCodexEmailCandidate(raw string) string {
	raw = strings.TrimSpace(raw)
	if raw == "" {
		return ""
	}

	if strings.HasSuffix(raw, "-team") {
		middle := strings.TrimSuffix(raw, "-team")
		if idx := strings.Index(middle, "-"); idx >= 0 && idx+1 < len(middle) {
			return middle[idx+1:]
		}
	}

	parts := strings.Split(raw, "-")
	if len(parts) > 1 {
		last := strings.ToLower(strings.TrimSpace(parts[len(parts)-1]))
		if _, ok := knownCodexPlanSuffixes[last]; ok {
			return strings.Join(parts[:len(parts)-1], "-")
		}
	}

	return raw
}

func normalizeCredentialFileName(fileName string) string {
	fileName = strings.TrimSpace(fileName)
	if fileName == "" {
		return ""
	}
	return filepath.Base(fileName)
}

func matchAccountsByCandidateNames(accounts []service.Account, candidateNames []string) []service.Account {
	if len(candidateNames) == 0 {
		return nil
	}

	candidateSet := make(map[string]struct{}, len(candidateNames))
	for _, candidateName := range candidateNames {
		candidateSet[strings.ToLower(strings.TrimSpace(candidateName))] = struct{}{}
	}

	matched := make([]service.Account, 0)
	for i := range accounts {
		account := accounts[i]
		if _, ok := candidateSet[strings.ToLower(strings.TrimSpace(account.Name))]; ok {
			matched = append(matched, account)
		}
	}
	return matched
}

func validateDataPayloadItems(payload DataPayload) error {
	for _, proxy := range payload.Proxies {
		if err := validateDataProxy(proxy); err != nil {
			return err
		}
	}
	for _, account := range payload.Accounts {
		if err := validateDataAccount(account); err != nil {
			return err
		}
	}
	return nil
}
