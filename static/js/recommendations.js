/**
 * Gemini AI Recommendations
 * Fetches and displays AI-powered product recommendations
 */

class GeminiRecommender {
    constructor(containerSelector = '#gemini-recommendations') {
        this.container = document.querySelector(containerSelector);
        this.loading = false;
    }

    /**
     * Fetch recommendations from the API
     */
    async fetchRecommendations() {
        if (this.loading || !this.container) return;

        this.loading = true;
        this.renderLoading();

        try {
            const response = await fetch('/api/recommendations/gemini/', {
                method: 'GET',
                headers: {
                    'Accept': 'application/json',
                    'X-Requested-With': 'XMLHttpRequest'
                },
                credentials: 'include'
            });

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }

            const data = await response.json();
            
            if (data.recommendations && data.recommendations.length > 0) {
                this.renderRecommendations(data.recommendations);
            } else {
                this.renderEmpty();
            }
        } catch (error) {
            console.error('Error fetching recommendations:', error);
            this.renderError(error.message);
        } finally {
            this.loading = false;
        }
    }

    /**
     * Render loading state
     */
    renderLoading() {
        this.container.innerHTML = `
            <div class="text-center py-4">
                <div class="spinner-border text-primary" role="status">
                    <span class="visually-hidden">Loading AI recommendations...</span>
                </div>
                <p class="mt-2 text-muted">✨ AI is analyzing your preferences...</p>
            </div>
        `;
    }

    /**
     * Render empty state
     */
    renderEmpty() {
        this.container.innerHTML = `
            <div class="alert alert-info">
                <i class="bi bi-info-circle me-2"></i>
                No recommendations available at this time. Explore more listings to get personalized suggestions!
            </div>
        `;
    }

    /**
     * Render error state
     */
    renderError(message) {
        this.container.innerHTML = `
            <div class="alert alert-warning">
                <i class="bi bi-exclamation-triangle me-2"></i>
                Could not generate recommendations: ${message}
            </div>
        `;
    }

    /**
     * Render recommendations list
     */
    renderRecommendations(recommendations) {
        const html = `
            <div class="recommendations-container">
                <div class="recommendations-header" style="margin-bottom: 1.5rem;">
                    <h3 style="font-weight: 700; color: var(--ubelt-navy); margin: 0; display: flex; align-items: center; gap: 0.5rem;">
                        <i class="bi bi-sparkles" style="color: #f9a825;"></i>
                        AI-Powered Recommendations
                    </h3>
                    <p style="color: #666; font-size: 0.9rem; margin-top: 0.25rem;">
                        Based on your favorite items, our AI picked these for you
                    </p>
                </div>
                <div class="recommendations-grid" style="display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 1.25rem;">
                    ${recommendations.map(rec => this.renderRecommendationCard(rec)).join('')}
                </div>
            </div>
        `;
        this.container.innerHTML = html;
    }

    /**
     * Render a single recommendation card
     */
    renderRecommendationCard(listing) {
        const schoolBadge = listing.school_name ? 
            `<span class="badge bg-light text-dark" style="font-size: 0.75rem; margin-top: 0.5rem;">
                <i class="bi bi-mortarboard me-1"></i>${listing.school_name}
            </span>` : '';

        const imageHtml = listing.image_url ?
            `<img src="${listing.image_url}" alt="${listing.title}" loading="lazy" style="width: 100%; height: 150px; object-fit: cover;">` :
            `<div style="width: 100%; height: 150px; background: #f0f0f0; display: flex; align-items: center; justify-content: center; color: #999;">
                <i class="bi bi-image" style="font-size: 2rem;"></i>
            </div>`;

        return `
            <a href="${listing.url}" style="text-decoration: none; color: inherit; cursor: pointer;" class="rec-card" 
               style="display: block; background: white; border-radius: 12px; overflow: hidden; border: 1px solid #e0e0e0; 
                      transition: all 0.3s ease; box-shadow: 0 2px 8px rgba(0,0,0,0.08);"
               onmouseover="this.style.boxShadow='0 8px 20px rgba(0,0,0,0.15)'; this.style.transform='translateY(-2px)'"
               onmouseout="this.style.boxShadow='0 2px 8px rgba(0,0,0,0.08)'; this.style.transform=''">
                <div style="background: #f9f9f9; position: relative; overflow: hidden;">
                    ${imageHtml}
                    <span class="badge bg-warning text-dark" style="position: absolute; top: 8px; right: 8px; font-size: 0.7rem;">
                        <i class="bi bi-star-fill"></i> AI Pick
                    </span>
                </div>
                <div style="padding: 1rem;">
                    <div style="font-weight: 600; color: var(--ubelt-teal); margin-bottom: 0.25rem;">
                        ₱${listing.price.toLocaleString('en-US', {minimumFractionDigits: 0, maximumFractionDigits: 2})}
                    </div>
                    <div style="font-weight: 500; font-size: 0.95rem; color: #1f1f1f; margin-bottom: 0.5rem; line-height: 1.3;">
                        ${listing.title}
                    </div>
                    ${schoolBadge}
                    <div style="font-size: 0.8rem; color: #97C2EC; margin-top: 0.75rem; font-style: italic; line-height: 1.3;">
                        💡 ${listing.ai_reason}
                    </div>
                </div>
            </a>
        `;
    }
}

// Auto-initialize when page loads
document.addEventListener('DOMContentLoaded', function() {
    const recommenderContainer = document.querySelector('#gemini-recommendations');
    if (recommenderContainer) {
        const recommender = new GeminiRecommender('#gemini-recommendations');
        recommender.fetchRecommendations();
        
        // Expose globally for manual refresh
        window.geminiRecommender = recommender;
    }
});
