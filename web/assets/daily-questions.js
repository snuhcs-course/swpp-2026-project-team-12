import { icon } from './icons.js';

const e = value => String(value ?? '').replace(/[&<>"']/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[ch]);
export const questionKinds = { choice: '밸런스 게임', text: '한 줄 답변', weather: '오늘의 마음 날씨', tier: '티어 리스트' };
export const answerChoice = answer => answer.choice === '기타' && answer.other_text ? `기타 · ${answer.other_text}` : answer.choice || '';
export const questionVersion = question => `${question.date}|${question.version}`;

export function questionPayload(question, draft) {
  const payload = { choice: '', other_text: '', text: (draft.text || '').trim(), tiers: {}, source: draft.source === 'voice' ? 'voice' : 'text' };
  if (payload.text.length > 1000) throw new Error('답변은 1,000자 이내로 적어 주세요.');
  if (['choice', 'weather'].includes(question.kind)) {
    if (!question.options.includes(draft.choice)) throw new Error('선택지 중 하나를 골라 주세요.');
    payload.choice = draft.choice;
    if (draft.choice === '기타') {
      payload.other_text = (draft.other_text || '').trim();
      if (!payload.other_text || payload.other_text.length > 100) throw new Error('기타 내용은 1~100자로 적어 주세요.');
    }
  } else if (question.kind === 'tier') {
    for (const option of question.options) {
      const grade = draft.tiers?.[option];
      if (!['S', 'A', 'B', 'C'].includes(grade)) throw new Error('모든 항목의 등급을 골라 주세요.');
      Object.defineProperty(payload.tiers, option, { value: grade, enumerable: true });
    }
  } else if (question.kind !== 'text' || !payload.text) throw new Error('가족에게 들려줄 답변을 적어 주세요.');
  return payload;
}

export function questionEntry(question, unread = false) {
  return `<button type="button" data-action="daily-open" class="daily-entry" aria-label="오늘의 질문: ${e(question?.title || '가족과 나눌 이야기를 확인해 보세요')}${unread ? ' · 새 이야기가 있어요' : ''}">
    <span class="daily-entry-icon">${icon('comment')}</span><span class="daily-entry-copy"><span>오늘의 질문${unread ? '<i class="daily-unread" aria-hidden="true"></i><span class="sr-only">새 이야기가 있어요</span>' : ''}</span><strong>${e(question?.title || '가족과 나눌 오늘의 질문을 확인해 보세요')}</strong></span><span class="daily-entry-cta">이야기 나누기</span>${icon('chevron')}</button>`;
}

function answerBody(answer) {
  return `${answerChoice(answer) ? `<strong class="daily-choice-chip">${e(answerChoice(answer))}</strong>` : ''}
    ${Object.keys(answer.tiers || {}).length ? `<div class="daily-tier-results">${Object.entries(answer.tiers).map(([option, grade]) => `<span><b>${e(grade)}</b>${e(option)}</span>`).join('')}</div>` : ''}
    ${answer.text ? `<p class="daily-answer-text">${e(answer.text)}</p>` : ''}`;
}

export function questionMarkup(question, userId, { editing, draft, comment = '' } = {}) {
  const mine = question.answers.find(answer => answer.author_id === userId);
  editing ??= !mine;
  draft ??= mine || {};
  const selected = editing ? draft.choice : mine?.choice;
  const choices = ['choice', 'weather'].includes(question.kind) ? `<fieldset class="daily-options"><legend class="sr-only">내 선택</legend>${question.options.map((option, index) => `
    <div class="daily-option${selected === option ? ' selected' : ''}"><label for="daily-option-${index}"><input id="daily-option-${index}" type="radio" name="choice" value="${e(option)}" ${selected === option ? 'checked' : ''} ${editing ? 'required' : 'disabled'}><span>${e(option)}</span></label>
    ${option === '기타' ? editing ? `<input name="other_text" aria-label="기타 내용" placeholder="직접 입력" maxlength="100" value="${e(draft.other_text)}" ${selected === '기타' ? 'required' : 'hidden disabled'}>` : selected === '기타' ? `<strong>${e(mine?.other_text)}</strong>` : '' : ''}</div>`).join('')}</fieldset>` : '';
  const tiers = question.kind === 'tier' ? `<fieldset class="daily-tiers"><legend>항목마다 등급을 골라 주세요.</legend><p class="help">S 꼭 하고 싶어요 · A 좋아요 · B 괜찮아요 · C 다음에</p>${question.options.map((option, index) => `<label><span>${e(option)}</span><select name="tier-${index}" required aria-label="${e(option)} 등급"><option value="">선택</option>${['S', 'A', 'B', 'C'].map(grade => `<option value="${grade}" ${draft.tiers?.[option] === grade ? 'selected' : ''}>${grade}</option>`).join('')}</select></label>`).join('')}</fieldset>` : '';
  return `<div class="daily-meta"><time datetime="${e(question.date)}">${e(question.date.replace(/^(\d{4})-(\d{2})-(\d{2})$/, '$1년 $2월 $3일'))}</time><button type="button" class="button quiet compact" data-action="daily-history">${icon('calendar')}지난 질문</button></div>
    <div class="daily-layout"><section class="daily-prompt"><span class="tag">${e(questionKinds[question.kind])}</span><h3 id="daily-question-title">${e(question.title)}</h3>
    ${editing ? `<form data-form="daily-answer" aria-labelledby="daily-question-title">${choices}${tiers}<label class="field"><span>${question.kind === 'text' ? '가족에게 내 이야기를 들려주세요' : '이유 한마디 (선택)'}</span><textarea name="text" rows="3" maxlength="1000" ${question.kind === 'text' ? 'required' : ''} placeholder="${question.kind === 'text' ? '짧은 이야기부터 편하게 적어 주세요.' : '왜 그렇게 생각했나요?'}">${e(draft.text)}</textarea></label><div class="form-error" role="alert"></div><div class="daily-submit"><button type="button" data-action="daily-record-answer" class="button quiet compact">${icon('mic')}말로 답하기</button><button type="submit" class="button primary compact">${mine ? '답변 수정하기' : '답변 남기기'}${icon('arrow')}</button></div><p class="help daily-note">답변은 우리 가족에게 보여요. 나중에 수정할 수 있어요.</p></form>` : `${choices}<div class="daily-own-heading"><strong>내 답변</strong><button type="button" data-action="daily-edit" class="button quiet compact">수정</button></div>${answerBody(mine)}`}</section>
    <section class="daily-conversation" aria-label="가족 이야기"><h3>가족 답변 <span>${question.answers.length}</span></h3><div class="daily-answers">${question.answers.length ? question.answers.map(answer => `<article class="daily-answer"><span class="avatar tone-${Math.abs(Number(answer.author_id) || 0) % 5} small" aria-hidden="true">${e([...answer.author_name][0])}</span><div><strong>${e(answer.author_name)}${answer.author_id === userId ? ' · 나' : ''}</strong>${answerBody(answer)}</div></article>`).join('') : '<p class="no-comments">가족의 첫 이야기를 기다리고 있어요.</p>'}</div>
    <section class="daily-comments"><h3>함께 이야기해요 <span>${question.comments.length}</span></h3><div>${question.comments.map(item => `<article class="comment"><div><strong>${e(item.author_name)}</strong><p>${e(item.text)}</p></div></article>`).join('') || '<p class="no-comments">다정한 한마디를 남겨보세요.</p>'}</div><form data-form="daily-comment"><label class="sr-only" for="daily-comment">댓글 남기기</label><textarea id="daily-comment" name="text" rows="2" maxlength="2000" required placeholder="가족과 함께 이야기해 보세요.">${e(comment)}</textarea><p class="form-error" role="alert"></p><div class="daily-submit"><button type="button" data-action="daily-record-comment" class="button quiet compact">${icon('mic')}말로 쓰기</button><button type="submit" class="button secondary compact">댓글 보내기${icon('arrow')}</button></div></form></section></section></div><div id="voice-panel" aria-live="polite"></div>`;
}

export function questionHistory(questions, nextBefore) {
  return `<div class="daily-history-heading"><h3>지난 질문</h3><button type="button" class="button quiet compact" data-action="daily-today">오늘의 질문으로${icon('arrow')}</button></div><div class="daily-history-list">${questions.map(item => `<button type="button" data-action="daily-detail" data-id="${Number(item.id)}"><span><time>${e(item.date)}</time><strong>${e(item.title)}</strong><small>${e(questionKinds[item.kind])}</small></span>${icon('chevron')}</button>`).join('') || '<p class="no-comments">아직 지난 질문이 없어요.</p>'}</div>${nextBefore ? `<button type="button" class="button secondary full" data-action="daily-more" data-before="${e(nextBefore)}">이전 질문 더 보기</button>` : ''}`;
}
