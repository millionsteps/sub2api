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

type deleteAccountsByFileNameResult struct {
	FileName          string   `json:"file_name"`
	Platform          string   `json:"platform,omitempty"`
	Type              string   `json:"type,omitempty"`
	CandidateNames    []string `json:"candidate_names,omitempty"`
	MatchedAccountIDs []int64  `json:"matched_account_ids,omitempty"`
	DeletedAccountIDs []int64  `json:"deleted_account_ids,omitempty"`
	Error             string   `json:"error,omitempty"`
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
	out := deleteAccountsByFileNamesResponse{
		RequestedFiles: len(req.FileNames),
		DryRun:         req.DryRun,
		Results:        make([]deleteAccountsByFileNameResult, 0, len(req.FileNames)),
	}

	accountCache := make(map[string][]service.Account)

	for _, rawFileName := range req.FileNames {
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
		}
		sort.Slice(result.MatchedAccountIDs, func(i, j int) bool {
			return result.MatchedAccountIDs[i] < result.MatchedAccountIDs[j]
		})

		if !req.DryRun {
			for _, account := range matchedAccounts {
				if err := h.adminService.DeleteAccount(ctx, account.ID); err != nil {
					result.Error = err.Error()
					break
				}
				result.DeletedAccountIDs = append(result.DeletedAccountIDs, account.ID)
				out.DeletedAccounts++
			}
		}

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
