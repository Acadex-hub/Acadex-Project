document.addEventListener('DOMContentLoaded', () => {
    const modal = document.getElementById('profile-edit-modal');
    const form = document.getElementById('profile-edit-form');
    const photoInput = document.getElementById('profile-photo-input');
    const message = document.getElementById('profile-save-message');
    const fields = {
        name: document.getElementById('profile-name-input'),
        institution: document.getElementById('profile-institution-input'),
        course: document.getElementById('profile-course-input'),
        year: document.getElementById('profile-year-input'),
        bio: document.getElementById('profile-bio-input'),
    };
    let profile = {
        userId: null,
        email: '',
        name: '',
        institution: '',
        course: '',
        year: '',
        bio: '',
        photo: '',
    };
    let draftPhoto = '';

    const getInitials = (name) => name.trim().split(/\s+/).slice(0, 2).map(part => part[0]).join('').toUpperCase() || '?';
    const yearLabel = (value) => ({
        '1': 'First year',
        '2': 'Second year',
        '3': 'Third year',
        '4': 'Fourth year',
        '5': 'Fifth year',
        '6': 'Postgraduate',
    }[value] || 'Student');

    const updateAvatar = (avatar, photo, name) => {
        const image = avatar.querySelector('[data-profile-image]');
        const initials = avatar.querySelector('[data-profile-initial]');
        avatar.classList.toggle('has-photo', Boolean(photo));
        initials.textContent = getInitials(name);
        if (photo) image.src = photo;
        else image.removeAttribute('src');
    };

    const renderProfile = () => {
        document.querySelectorAll('[data-profile-name]').forEach(element => {
            element.textContent = profile.name || 'Student';
        });
        document.querySelectorAll('[data-profile-email]').forEach(element => {
            element.textContent = profile.email;
        });
        document.querySelectorAll('[data-profile-course]').forEach(element => {
            element.textContent = profile.course || 'Course not set';
        });
        document.querySelectorAll('[data-profile-year]').forEach(element => {
            element.textContent = yearLabel(profile.year);
        });
        document.querySelectorAll('[data-profile-institution]').forEach(element => {
            element.textContent = profile.institution;
            element.hidden = !profile.institution;
        });
        document.querySelectorAll('[data-profile-bio]').forEach(element => {
            element.textContent = profile.bio;
            element.hidden = !profile.bio;
        });
        document.querySelectorAll('[data-profile-avatar]').forEach(avatar => {
            updateAvatar(avatar, profile.photo, profile.name || 'Student');
        });
    };

    const openProfileEditor = () => {
        fields.name.value = profile.name;
        fields.institution.value = profile.institution;
        fields.course.value = profile.course;
        fields.year.value = profile.year;
        fields.bio.value = profile.bio;
        draftPhoto = profile.photo;
        updateAvatar(modal.querySelector('[data-profile-avatar]'), draftPhoto, profile.name);
        message.textContent = '';
        modal.hidden = false;
        fields.name.focus();
    };

    const closeProfileEditor = () => {
        modal.hidden = true;
        message.textContent = '';
        photoInput.value = '';
    };

    const createCompressedPhoto = async (file) => {
        if (!file.type.startsWith('image/')) {
            throw new Error('Choose an image file.');
        }
        if (file.size > 8 * 1024 * 1024) {
            throw new Error('Choose an image smaller than 8 MB.');
        }

        const bitmap = await createImageBitmap(file);
        const scale = Math.min(1, 512 / Math.max(bitmap.width, bitmap.height));
        const canvas = document.createElement('canvas');
        canvas.width = Math.max(1, Math.round(bitmap.width * scale));
        canvas.height = Math.max(1, Math.round(bitmap.height * scale));
        const context = canvas.getContext('2d');
        context.fillStyle = '#ffffff';
        context.fillRect(0, 0, canvas.width, canvas.height);
        context.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
        bitmap.close();
        return canvas.toDataURL('image/jpeg', 0.82);
    };

    const loadSignedInProfile = async () => {
        try {
            const response = await fetch('/api/me', { credentials: 'same-origin' });
            if (!response.ok) {
                window.location.replace('/indext.html?tab=login');
                return;
            }
            const account = await response.json();
            if (account.role !== 'student') {
                window.location.replace('/AdminPage.html');
                return;
            }

            profile = {
                userId: account.user_id,
                email: account.email,
                name: account.full_name,
                institution: account.institution || '',
                course: account.course_of_study || '',
                year: account.year_of_study == null ? '' : String(account.year_of_study),
                bio: account.bio || '',
                photo: '',
            };
            try {
                profile.photo = window.localStorage.getItem(`acadex-profile-photo:${profile.userId}`) || '';
            } catch {
                profile.photo = '';
            }
            renderProfile();
        } catch {
            document.querySelectorAll('[data-profile-name]').forEach(element => {
                element.textContent = 'Profile unavailable';
            });
        }
    };

    window.openProfileEditor = openProfileEditor;
    document.getElementById('cancel-profile-editor').addEventListener('click', closeProfileEditor);
    document.getElementById('close-profile-editor').addEventListener('click', closeProfileEditor);
    document.getElementById('remove-profile-photo').addEventListener('click', () => {
        draftPhoto = '';
        photoInput.value = '';
        updateAvatar(modal.querySelector('[data-profile-avatar]'), '', fields.name.value);
        message.textContent = 'Photo will be removed when you save.';
    });

    fields.name.addEventListener('input', () => {
        updateAvatar(modal.querySelector('[data-profile-avatar]'), draftPhoto, fields.name.value);
    });

    photoInput.addEventListener('change', async () => {
        const file = photoInput.files[0];
        if (!file) return;
        message.textContent = 'Preparing image...';
        try {
            draftPhoto = await createCompressedPhoto(file);
            updateAvatar(modal.querySelector('[data-profile-avatar]'), draftPhoto, fields.name.value);
            message.textContent = 'Image ready. Save changes to use this photo.';
        } catch (error) {
            photoInput.value = '';
            message.textContent = error.message || 'This image could not be opened.';
        }
    });

    form.addEventListener('submit', async (event) => {
        event.preventDefault();
        const updatedProfile = {
            ...profile,
            name: fields.name.value.trim(),
            institution: fields.institution.value.trim(),
            course: fields.course.value.trim(),
            year: fields.year.value,
            bio: fields.bio.value.trim(),
            photo: draftPhoto,
        };

        message.textContent = 'Saving profile...';
        try {
            const response = await fetch('/api/profile', {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'same-origin',
                body: JSON.stringify({
                    full_name: updatedProfile.name,
                    institution: updatedProfile.institution,
                    course_of_study: updatedProfile.course,
                    year_of_study: updatedProfile.year,
                    bio: updatedProfile.bio,
                }),
            });
            const result = await response.json();
            if (!response.ok) throw new Error(result.message || 'Could not save the profile.');
        } catch (error) {
            message.textContent = error.message || 'Could not save the profile.';
            return;
        }

        profile = updatedProfile;
        try {
            const photoKey = `acadex-profile-photo:${profile.userId}`;
            if (profile.photo) window.localStorage.setItem(photoKey, profile.photo);
            else window.localStorage.removeItem(photoKey);
        } catch {
            message.textContent = 'Profile saved, but the photo could not be stored on this device.';
        }
        renderProfile();
        closeProfileEditor();
    });

    modal.addEventListener('click', (event) => {
        if (event.target === modal) closeProfileEditor();
    });
    document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape' && !modal.hidden) closeProfileEditor();
    });

    loadSignedInProfile();
});
